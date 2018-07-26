#
# Copyright (C) 2018 ETH Zurich and University of Bologna
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# Authors: Germain Haugou, ETH (germain.haugou@iis.ee.ethz.ch)

import ctypes
import os
import os.path
import json_tools as js
from elftools.elf.elffile import ELFFile
import time


class Ctype_cable(object):

    def __init__(self, module, config, system_config):

        self.module = module
        self.gdb_handle = None

        # Register entry points with appropriate arguments
        self.module.cable_new.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self.module.cable_write.argtypes = \
            [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
        self.module.cable_read.argtypes = \
            [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
        self.module.cable_jtag_get_reg.argtypes = \
            [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]

        config_string = None

        if config is not None:
            config_string = config.dump_to_string().encode('utf-8')

        self.instance = self.module.cable_new(config_string, system_config.dump_to_string().encode('utf-8'))

        if self.instance == 0:
            raise Exception('Failed to initialize cable with error: ' + self.module.bridge_get_error().decode('utf-8'))

    def get_instance(self):
        return self.instance

    def write(self, addr, size, buffer):
        data = (ctypes.c_char * size).from_buffer(bytearray(buffer))
        self.module.cable_write(self.instance, addr, size, data)

    def read(self, addr, size):
        data = (ctypes.c_char * size)()
        self.module.cable_read(self.instance, addr, size, data)

        result = []
        for elem in data:
            result.append(elem)

        return result

    def chip_reset(self, value):
        self.module.chip_reset(self.instance, value)

    def jtag_reset(self, value):
        self.module.jtag_reset(self.instance, value)

    def jtag_soft_reset(self):
        self.module.jtag_soft_reset(self.instance)

    def jtag_set_reg(self, reg, width, value):
        self.module.cable_jtag_set_reg(self.instance, reg, width, value)

    def jtag_get_reg(self, reg, width, value):
        out_value = ctypes.c_int()
        self.module.cable_jtag_get_reg(self.instance, reg, width, ctypes.byref(out_value), value)
        return out_value.value

    def lock(self):
        self.module.cable_lock(self.instance)

    def unlock(self):
        self.module.cable_unlock(self.instance)




class debug_bridge(object):

    def __init__(self, config, binaries=[], verbose=False, fimages=[]):
        self.config = config
        self.cable = None
        self.cable_name = config.get('**/debug-bridge/cable/type').get()
        self.binaries = binaries
        self.fimages = fimages
        self.ioloop_handle = None
        self.reqloop_handle = None
        self.verbose = verbose
        self.gdb_handle = None
        self.cable_config = config.get('**/debug-bridge/cable')



        # Load the library which provides generic services through
        # python / C++ bindings
        lib_path=os.path.join('libpulpdebugbridge.so')
        self.module = ctypes.CDLL(lib_path)
        self.module.bridge_ioloop_close.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.module.bridge_reqloop_close.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.module.bridge_get_error.restype = ctypes.c_char_p

        self.module.bridge_init(config.dump_to_string().encode('utf-8'), verbose)

        #self.module.jtag_shift.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_char_p)]

    def __mount_cable(self):
        if self.cable_name is None:
            raise Exception("Trying to mount cable while no cable was specified")

        if self.cable_name.split('@')[0] in ['ftdi', 'jtag-proxy']:
            self.__mount_ctype_cable()
            pass
        else:
            raise Exception('Unknown cable: ' + self.cable_name)

    def __mount_ctype_cable(self):

        self.cable = Ctype_cable(
            module = self.module,
            config = self.cable_config,
            system_config = self.config
        )

    def get_cable(self):
        if self.cable is None:
            self.__mount_cable()

        return self.cable

    def load_jtag(self):
        raise Exception('JTAG boot is not supported on this target')

    def load_jtag_hyper(self):
        raise Exception('JTAG boot is not supported on this target')

    def load_elf(self, binary):
        with open(binary, 'rb') as file:
            elffile = ELFFile(file)

            for segment in elffile.iter_segments():

                if segment['p_type'] == 'PT_LOAD':

                    data = segment.data()
                    addr = segment['p_paddr']
                    size = len(data)

                    if self.verbose:
                        print ('Loading section (base: 0x%x, size: 0x%x)' % (addr, size))

                    self.write(addr, size, data)

                    if segment['p_filesz'] < segment['p_memsz']:
                        addr = segment['p_paddr'] + segment['p_filesz']
                        size = segment['p_memsz'] - segment['p_filesz']
                        print ('Init section to 0 (base: 0x%x, size: 0x%x)' % (addr, size))
                        self.write(
                            addr,
                            size,
                            [0] * size
                        )
        return 0

    def load(self):
        mode = self.config.get('**/debug-bridge/boot-mode').get()
        if mode == 'jtag':
            return self.load_jtag()
        elif mode == 'jtag_hyper':
            return self.load_jtag_hyper()
        else:
            return self.load_default()

    def load_default(self):
        self.reset()

        for binary in self.binaries:
            if self.load_elf(binary=binary):
                return 1

        return 0

    def start(self):
        return 0

    def read(self, addr, size):
        return self.get_cable().read(addr, size)

    def write(self, addr, size, buffer):
        return self.get_cable().write(addr, size, buffer)

    def write_int(self, addr, value, size):
        return self.write(addr, size, value.to_bytes(size, byteorder='little'))

    def write_32(self, addr, value):
        return self.write_int(addr, value, 4)

    def write_16(self, addr, value):
        return self.write_int(addr, value, 2)

    def write_8(self, addr, value):
        return self.write_int(addr, value, 1)

    def read_int(self, addr, size):
        byte_array = None
        for byte in self.read(addr, size):
            if byte_array == None:
                byte_array = byte
            else:
                byte_array += byte
        return int.from_bytes(byte_array, byteorder='little')

    def read_32(self, addr):
        return self.read_int(addr, 4)

    def read_16(self, addr):
        return self.read_int(addr, 2)

    def read_8(self, addr):
        return self.read_int(addr, 1)

    def __get_binary_symbol_addr(self, name):
        for binary in self.binaries:
            with open(binary, 'rb') as file:
                elf = ELFFile(file)
                for section in elf.iter_sections():
                    if section.header['sh_type'] == 'SHT_SYMTAB':
                        for symbol in section.iter_symbols():
                            if symbol.name == name:
                                t_section=symbol.entry['st_shndx']
                                t_vaddr=symbol.entry['st_value']
                                return t_vaddr
        return 0

    def reset(self):
        self.get_cable().jtag_reset(True)
        self.get_cable().jtag_reset(False)
        self.get_cable().chip_reset(True)
        self._iet_cable().chip_reset(False)
        return 0

    def ioloop(self):

        # First get address of the structure used to communicate between
        # the bridge and the runtime
        addr = self.__get_binary_symbol_addr('__rt_debug_struct_ptr')
        if addr == 0:
            addr = self.__get_binary_symbol_addr('debugStruct_ptr')

        self.ioloop_handle = self.module.bridge_ioloop_open(
            self.get_cable().get_instance(), addr)

        return 0

    def reqloop(self):

        # First get address of the structure used to communicate between
        # the bridge and the runtime
        addr = self.__get_binary_symbol_addr('__rt_debug_struct_ptr')
        if addr == 0:
            addr = self.__get_binary_symbol_addr('debugStruct_ptr')

        self.reqloop_handle = self.module.bridge_reqloop_open(
            self.get_cable().get_instance(), addr)

        return 0



    def gdb(self, port):
        self.gdb_handle = self.module.gdb_server_open(self.get_cable().get_instance(), port)
        return 0

    def flash(self):
        MAX_BUFF_SIZE = (350*1024)
        f_path = self.fimages[0]
        addrHeader = self.__get_binary_symbol_addr('flasherHeader')
        addrImgRdy = addrHeader
        addrFlasherRdy = addrHeader + 4
        addrFlashAddr = addrHeader + 8
        addrIterTime = addrHeader + 12
        addrBufSize = addrHeader + 16
        # open the file in read binary mode
        f_img = open(f_path, 'rb')
        f_size = os.path.getsize(f_path)
        lastSize = f_size % MAX_BUFF_SIZE;
        if(lastSize):
            n_iter = f_size // MAX_BUFF_SIZE + 1;
        else:
            n_iter = f_size // MAX_BUFF_SIZE

        flasher_ready = self.read_32(addrFlasherRdy)
        while(flasher_ready == 0):
            flasher_ready = self.read_32(addrFlasherRdy)
        flasher_ready = 0;
        addrBuffer = self.read_32((addrHeader+20))
        indexAddr = 0
        self.write_32(addrFlashAddr, 0)
        self.write_32(addrIterTime, n_iter)
        for i in range(n_iter):
            if (lastSize and i == (n_iter-1)):
                buff_data = f_img.read(lastSize)
                self.write(addrBuffer, lastSize, buff_data)
                self.write_32(addrBufSize, ((lastSize + 3) & ~3))
            else:
                buff_data = f_img.read(MAX_BUFF_SIZE)
                self.write(addrBuffer, MAX_BUFF_SIZE, buff_data)
                self.write_32(addrBufSize, MAX_BUFF_SIZE)
            self.write_32(addrImgRdy, 1)
            self.write_32(addrFlasherRdy, 0)
            if (i!=(n_iter-1)):
                flasher_ready = self.read_32(addrFlasherRdy)
                while(flasher_ready == 0):
                    flasher_ready = self.read_32(addrFlasherRdy)
        f_img.close()
        return 0

    def wait(self):
        if self.gdb_handle is not None:
            self.module.gdb_server_close(self.gdb_handle, 0)

        # The wait function returns in case ioloop has been launched
        # as it will check for end of application.
        # Otherwise it will wait for reqloop for ever
        if self.ioloop_handle is not None:
            self.module.bridge_ioloop_close(self.ioloop_handle, 0)
            return 0

        if self.reqloop_handle is not None:
            self.module.bridge_reqloop_close(self.reqloop_handle, 0)

        return 0

    def lock(self):
        self.get_cable().lock()

    def unlock(self):
        self.get_cable().unlock()
