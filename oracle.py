#!/usr/bin/env python3

import asyncio, datetime, pysodium, os, binascii, shutil, sphinx, sys

verbose = False
address = '127.0.0.1'
port = 2355
datadir = 'data/'
keydir = '~/.sphinx/'
key = None

CREATE=0x00
GET=0x66
CHANGE=0xaa
DELETE=0xff

def respond(chal, id):
  keyf = datadir+binascii.hexlify(id).decode()+'/key'
  if not os.path.exists(keyf):
    print(keyf,'not exist')
    return b'fail' # key not found

  with open(keyf,'rb') as fd:
    secret = fd.read()

  if len(secret)!= sphinx.DECAF_255_SCALAR_BYTES:
    return b'fail'

  try:
    return sphinx.respond(chal, secret)
  except ValueError:
    return b'fail'

class SphinxOracleProtocol(asyncio.Protocol):
  def connection_made(self, transport):
    if verbose:
      peername = transport.get_extra_info('peername')
      print('{} Connection from {}'.format(datetime.datetime.now(), peername))
    self.transport = transport

  def create(self, data):
    # needs pubkey, id, challenge, sig(id)
    # returns output from ./response | fail
    pk = data[129:161]
    try:
      data = pysodium.crypto_sign_open(data, pk)
    except ValueError:
      print('invalid signature')
      return b'fail'
    id = data[1:33]
    chal = data[33:65]
    tdir = datadir+binascii.hexlify(id).decode()

    if os.path.exists(tdir):
      print(tdir, 'exists')
      return b'fail' # key already exists

    os.mkdir(tdir,0o700)

    with open(tdir+'/pub','wb') as fd:
      os.fchmod(fd.fileno(),0o600)
      fd.write(pk)

    key=pysodium.randombytes(32)
    with open(tdir+'/key','wb') as fd:
      os.fchmod(fd.fileno(),0o600)
      fd.write(key)

    return respond(chal, id)

  def getpk(self,data):
    id = data[65:97]
    tdir = datadir+binascii.hexlify(id).decode()
    with open(tdir+'/pub','rb') as fd:
      return fd.read()

  def get(self, data):
    # needs id, challenge, sig(id)
    # returns output from ./response | fail
    try:
      pk = self.getpk(data)
    except:
      return b'fail'
    try:
      data = pysodium.crypto_sign_open(data, pk)
    except ValueError:
      print('invalid signature')
      return b'fail'
    id = data[1:33]
    chal = data[33:65]

    return respond(chal, id)

  def change(self, data):
    # needs id, challenge, sig(id)
    # returns output from ./response | fail
    try:
      pk = self.getpk(data)
    except:
      return b'fail'
    try:
      data = pysodium.crypto_sign_open(data, pk)
    except ValueError:
      print('invalid signature')
      return b'fail'
    id = data[1:33]
    chal = data[33:65]

    tdir = datadir+binascii.hexlify(id).decode()
    key=pysodium.randombytes(32)
    with open(tdir+'/key','wb') as fd:
      os.fchmod(fd.fileno(),0o600)
      fd.write(key)

    return respond(chal, id)

  def delete(self, data):
    # needs id, sig(id)
    # returns ok | fail
    try:
      pk = self.getpk(data)
    except:
      return b'fail'
    try:
      data = pysodium.crypto_sign_open(data, pk)
    except ValueError:
      print('invalid signature')
      return b'fail'
    id = data[1:33]

    tdir = datadir+binascii.hexlify(id).decode()
    shutil.rmtree(tdir)
    return b'ok'

  def data_received(self, data):
    res = b''

    if verbose:
      print('Data received: {!r}'.format(data))

    if data[64] == 0:
      res = self.create(data)
    elif data[64] == GET:
      # needs id, challenge, sig(id)
      # returns output from ./response | fail
      res = self.get(data)
    elif data[64] == CHANGE:
      # needs id, challenge, sig(id)
      # changes stored secret
      # returns output from ./response | fail
      res = self.change(data)
    elif data[64] == DELETE:
      # needs id, sig(id)
      # returns ok|fail
      res = self.delete(data)

    if verbose:
      print('Send: {!r}'.format(res))

    res=pysodium.crypto_sign(res,key)
    self.transport.write(res)

    if verbose:
      print('Close the client socket')
    self.transport.close()

def getkey(keydir):
  datadir = os.path.expanduser(keydir)
  try:
    with open(datadir+'server-key', 'rb') as fd:
      key = fd.read()
    return key
  except FileNotFoundError:
    print("no server key found, generating...")
    if not os.path.exists(datadir):
      os.mkdir(datadir,0o700)
    pk, sk = pysodium.crypto_sign_keypair()
    with open(datadir+'server-key','wb') as fd:
      os.fchmod(fd.fileno(),0o600)
      fd.write(sk)
    with open(datadir+'server-key.pub','wb') as fd:
      fd.write(pk)
    print("please share `%s` with all clients"  % (datadir+'server-key.pub'))
    return sk

if __name__ == '__main__':
  loop = asyncio.get_event_loop()
  # Each client connection will create a new protocol instance
  coro = loop.create_server(SphinxOracleProtocol, address, port)
  server = loop.run_until_complete(coro)

  key = getkey(keydir)
  if key == None:
    print("no signing key available.\nabort")
    sys.exit(1)

  # Serve requests until Ctrl+C is pressed
  if verbose:
    print('Serving on {}'.format(server.sockets[0].getsockname()))
  try:
    loop.run_forever()
  except KeyboardInterrupt:
    pass

  # Close the server
  server.close()
  loop.run_until_complete(server.wait_closed())
  loop.close()
