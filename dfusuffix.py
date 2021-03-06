import sys, struct, binascii, os.path, json, uuid, base64, StringIO

class YbPrefix:
    def __init__(self):
        self.data = []

    def __len__(self):
        return sum((4 + len(val) for key, val in self.data))

    def clear(self):
        del self.data[:]

    def load(self, stream):
        data = []
        while True:
            size, key = struct.unpack('<BB', stream[:2])
            value = stream[2:size+1]
            data.append((key, value))
            stream = stream[size+1:]
            if key == 0:
                break
        self.data = data

    def store(self, padding=None):
        unpadded = ''.join((struct.pack('<BB', 1+len(value), key) + value for key, value in self.data)) + '\x00'

        total_size = len(unpadded)
        pad = 0
        if padding:
            inverse_gap = total_size % padding
            if inverse_gap:
                pad = padding - inverse_gap

        return unpadded + '\x00'*pad

    def add(self, key, value):
        self.data.append((key, value))

    def finish(self, padding=None):
        total_size = 4 + sum((4 + len(val) for key, val in self.data))

        pad = 0
        if padding:
            inverse_gap = total_size % padding
            if inverse_gap:
                pad = padding - inverse_gap

        self.data.append((0, '\x00'*pad))

class Suffix:
    er_ok = 0
    er_not_a_suffix = 1
    er_invalid_crc = 2

    def __init__(self, idVendor=0xFFFF, idProduct=0xFFFF, bcdDevice=0xFFFF):
        self.bcdDFU = 0x100
        self.idVendor = idVendor
        self.idProduct = idProduct
        self.bcdDevice = bcdDevice
        self.extra = ''

    def __len__(self):
        return 0x10 + len(self.extra)

    @staticmethod
    def _calc_crc(s, seed=0xffffffff):
        return (binascii.crc32(s, seed^0xffffffff) & 0xffffffff) ^ 0xffffffff

    def load(self, s, check_crc=False):
        if len(s) < 0x10:
            return self.er_not_a_suffix
        unpacked = struct.unpack('<HHHHBBBBI', s[-0x10:])
        if unpacked[4:7] != (0x55, 0x46, 0x44) or unpacked[7] < 0x10 or unpacked[7] > len(s):
            return self.er_not_a_suffix

        if check_crc:
            if self._calc_crc(s[:-4]) != unpacked[8]:
                return self.er_invalid_crc

        self.bcdDevice, self.idProduct, self.idVendor, self.bcdDFU = unpacked[0:4]
        self.extra = s[-unpacked[7]:-0x10]
        return self.er_ok

    def store(self, s):
        part = self.extra + struct.pack('<HHHHBBBB',
            self.bcdDevice, self.idProduct, self.idVendor, self.bcdDFU,
            0x55, 0x46, 0x44, 0x10 + len(self.extra))

        crc = self._calc_crc(s)
        crc = self._calc_crc(part, crc)
        return s + part + struct.pack('<I', crc)

def add_suffix(fin, fout, idVendor, idProduct, bcdDevice, force=False):
    data = fin.read()

    if not force:
        suf = Suffix()
        if suf.load(data) == Suffix.er_ok:
            print >>sys.stderr, 'There already seems to be a suffix in the file (--force to override).'
            return 1

    suf = Suffix(idVendor, idProduct, bcdDevice)
    data = suf.store(data)

    fout.write(data)
    return 0

def verify_suffix(input, idVendor, idProduct, bcdDevice):
    with open(input, 'rb') as fin:
        data = fin.read()

    suf = Suffix()
    res = suf.load(data, check_crc=True)

    if res == Suffix.er_not_a_suffix:
        print 'The file doesn\'t seem to have a suffix.'
        return 1

    if res == Suffix.er_invalid_crc:
        print 'There seems to be a DFU suffix, but the CRC is invalid.'
        return 2

    print 'idVendor  = 0x%04x' % suf.idVendor
    print 'idProduct = 0x%04x' % suf.idProduct
    print 'bcdDevice = 0x%04x' % suf.bcdDevice

    if (suf.idVendor, suf.idProduct) == (0x4a61, 0x679c):
        yb_prefix = YbPrefix()
        yb_prefix.load(data)
        for key, value in yb_prefix.data:
            if key == 1:
                print 'yb:device_guid = %s' % ''.join(['%02x' % v for v in value])
            elif key == 2:
                print 'yb:fw_timestamp = %s' % datetime.fromtimestamp(struct.unpack('<I', value)[0]).ctime()
            elif key != 0:
                print 'yb:%04x = %s' % (key, base64.b16encode(value[:32]))

    return 0

def remove_suffix(input, output, idVendor, idProduct, bcdDevice, force):
    with open(input, 'rb') as fin:
        data = fin.read()

    suf = Suffix()
    res = suf.load(data, check_crc=True)

    if res == Suffix.er_not_a_suffix:
        print 'The file doesn\'t seem to have a suffix.'
        return 1

    if res == Suffix.er_invalid_crc:
        print 'There seems to be a DFU suffix, but the CRC is invalid.'
        return 2

    data = data[0:-len(suf)]
    with open(output, 'wb') as fout:
        fout.write(data)
    return 0

def _main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('output', nargs='?')
    ap.add_argument('--vidpid', '-v', default='FFFF:FFFF:FFFF')
    ap.add_argument('--add', '-A', action='store_true', default=False)
    ap.add_argument('--remove', '-R', action='store_true', default=False)
    ap.add_argument('--force', '-f', action='store_true', default=False)
    args = ap.parse_args()

    try:
        vidpid = [int(v, 16) for v in args.vidpid.split(':')]
    except ValueError:
        print >>sys.stderr, 'Invalid value: %s' % args.vidpid
        return 1

    if len(vidpid) == 2:
        idVendor, idProduct = vidpid
        bcdDevice = 0xFFFF
    elif len(vidpid) == 3:
        idVendor, idProduct, bcdDevice = vidpid
    else:
        print >>sys.stderr, '--vidpid must be either vid:pid or vid:pid:rev'
        return 1

    if not args.output:
        args.output = args.input

    if args.add:
        ff = StringIO.StringIO()
        with open(args.input, 'rb') as fin:
            res = add_suffix(fin, ff, idVendor, idProduct, bcdDevice, args.force)
        with open(args.output, 'wb') as fout:
            fout.write(ff)
    elif args.remove:
        return remove_suffix(args.input, args.output, idVendor, idProduct, bcdDevice, args.force)
    else:
        return verify_suffix(args.input, idVendor, idProduct, bcdDevice)

    return res

if __name__ == '__main__':
    sys.exit(_main())
