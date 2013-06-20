# Raise ImportError if we cannot find CUDA Driver.

from llvm import core as _lc
import numpy as np
from ctypes import *
from numbapro.cudadrv import driver as _cuda
from numbapro.cudadrv import devicearray
from numbapro import cuda
import math
import re

class CudaUFuncDispatcher(object):
    """
    Invoke the CUDA ufunc specialization for the given inputs.
    """
    def __init__(self, types_to_retty_kernels):
        self.functions = types_to_retty_kernels

    def _set_max_blocksize(self, blksz):
        self.__max_blocksize = blksz

    def _get_max_blocksize(self):
        try:
            return self.__max_blocksize
        except AttributeError:
            return 2**30 # a very large number

    def _del_max_blocksize(self, blksz):
        del self.__max_blocksize

    max_blocksize = property(_get_max_blocksize, _set_max_blocksize,
                             _del_max_blocksize)

    def _prepare_inputs(self, args):
        # prepare broadcasted contiguous arrays
        # TODO: Allow strided memory (use mapped memory + strides?)
        # TODO: don't perform actual broadcasting, pass in strides
        #        args = [np.ascontiguousarray(a) for a in args]

        return np.broadcast_arrays(*args)

    def _adjust_dimension(self, broadcast_arrays):
        '''Reshape the broadcasted arrays so that they are all 1D arrays.
        Uses ndarray.ravel() to flatten.  It only copy if necessary.
        '''
        reshape = broadcast_arrays[0].shape
        for i, ary in enumerate(broadcast_arrays):
            if ary.ndim > 1: # flatten multi-dimension arrays
                broadcast_arrays[i] = ary.ravel() # copy if necessary
        return broadcast_arrays

    def _allocate_output(self, broadcast_arrays, result_dtype):
        # return np.empty_like(broadcast_arrays[0], dtype=result_dtype)
        # for numpy1.5
        return np.empty(broadcast_arrays[0].shape, dtype=result_dtype)

    def __call__(self, *args, **kws):
        '''
        *args: numpy arrays or DeviceArrayBase (created by cuda.to_device).
               Cannot mix the two types in one call.

        **kws:
            stream -- cuda stream; when defined, asynchronous mode is used.
            out    -- output array. Can be a numpy array or DeviceArrayBase
                      depending on the input arguments.  Type must match
                      the input arguments.
        '''
        accepted_kws = 'stream', 'out'
        unknown_kws = [k for k in kws if k not in accepted_kws]
        assert not unknown_kws, ("Unknown keyword args %s" % unknown_kws)

        stream = kws.get('stream', 0)

        # convert arguments to ndarray if they are not
        args = list(args) # convert to list
        has_device_array_arg = any(devicearray.is_cuda_ndarray(v)
                                   for v in args)

        for i, arg in enumerate(args):
            if not isinstance(arg, np.ndarray) and \
                    not devicearray.is_cuda_ndarray(arg):
                args[i] = ary = np.asarray(arg)

        # get the dtype for each argument
        def _get_dtype(x):
            try:
                return x.dtype
            except AttributeError:
                return np.dtype(type(x))

        dtypes = tuple(_get_dtype(a) for a in args)

        # find the fitting function
        result_dtype, cuda_func = self._get_function_by_dtype(dtypes)
        MAX_THREAD = min(cuda_func.device.MAX_THREADS_PER_BLOCK,
                         self.max_blocksize)

        if has_device_array_arg:
            # Ugly: convert array scalar into zero-strided one element array.
            for i, ary in enumerate(args):
                if not ary.shape:
                    data = np.asscalar(ary)
                    ary = np.ndarray(shape=(1,), strides=(0,))
                    ary[0] = data
                    args[i] = ary

            # NOTE: When using DeviceArrayBase,
            #       it is assumed to be properly broadcasted.
            self._arguments_requirement(args)

            args, argconv = zip(*(cuda._auto_device(a) for a in args))
    
            element_count = self._determine_element_count(args)
            nctaid, ntid = self._determine_dimensions(element_count, MAX_THREAD)
            
            griddim = (nctaid,)
            blockdim = (ntid,)

            if 'out' not in kws:
                #out = self._allocate_output(args, result_dtype)
                #np.empty(args[0].shape[0], dtype=result_dtype)
                #device_out = cuda.to_device(out, stream, copy=False)
                out_shape = self._determine_output_shape(args)
                device_out = cuda.device_array(shape=out_shape,
                                               dtype=result_dtype,
                                               stream=stream)
            else:
                device_out = kws['out']
                assert devicearray.is_cuda_ndarray(device_out)
            kernel_args = list(args) + [device_out, element_count]

            cuda_func[griddim, blockdim, stream](*kernel_args)

#            for ary, conv in zip(args, argconv):
#                if conv:
#                    ary.to_host()
            return device_out

        else:
            broadcast_arrays = self._prepare_inputs(args)
            element_count = self._determine_element_count(broadcast_arrays)

            if 'out' not in kws:
                out = self._allocate_output(broadcast_arrays, result_dtype)
            else:
                out = kws['out']
                assert not devicearray.is_cuda_ndarray(device_out)
                assert out.shape[0] >= broadcast_arrays[0].shape[0]

            # Reshape the arrays if necessary.
            # Ufunc expects 1D array.
            reshape = out.shape
            (out,) = self._adjust_dimension([out])
            broadcast_arrays = self._adjust_dimension(broadcast_arrays)

            nctaid, ntid = self._determine_dimensions(element_count, MAX_THREAD)

            assert all(isinstance(array, np.ndarray)
                       for array in broadcast_arrays)

            device_ins = [cuda.to_device(x, stream) for x in broadcast_arrays]
            device_out = cuda.to_device(out, stream, copy=False)

            kernel_args = device_ins + [device_out, element_count]

            griddim = (nctaid,)
            blockdim = (ntid,)

            cuda_func[griddim, blockdim, stream](*kernel_args)
            
            device_out.to_host(stream) # only retrive the last one
            # Revert the shape of the array if it has been modified earlier
            return out.reshape(reshape)


    def _determine_output_shape(self, broadcast_arrays):
        return broadcast_arrays[0].shape

    def _get_function_by_dtype(self, dtypes):
        try:
            result_dtype, cuda_func = self.functions[dtypes]
            return result_dtype, cuda_func
        except KeyError:
            raise TypeError("Input dtypes not supported by ufunc %s" %
                            (dtypes,))
    
    def _determine_element_count(self, broadcast_arrays):
        return np.prod(broadcast_arrays[0].shape)

    def _arguments_requirement(self, args):
        assert args[0].ndim == 1
        # Accept same shape or array scalar
        assert all(x.shape == args[0].shape or
                   (x.strides == (0,) and x.shape == (1,))
                   for x in args)

    def _determine_dimensions(self, n, max_thread):
        # determine grid and block dimension
        thread_count =  min(max_thread, n)
        block_count = int(math.ceil(float(n) / max_thread))
        return block_count, thread_count

    def reduce(self, arg, stream=0):
        assert len(self.functions.keys()[0]) == 2, "Must be a binary ufunc"
        assert arg.ndim == 1

        n = arg.shape[0]
        gpu_mems = []

        if n == 0:
            raise TypeError("Reduction on an empty array.")
        elif n == 1:    # nothing to do
            return arg[0]

        # always use a stream
        stream = stream or cuda.stream()
        with stream.auto_synchronize():
            # transfer memory to device if necessary
            if devicearray.is_cuda_ndarray(arg):
                mem = arg
            else:
                mem = cuda.to_device(arg, stream)
            # do reduction
            out = self.__reduce(mem, gpu_mems, stream)
            # use a small buffer to store the result element
            buf = np.array((1,), dtype=arg.dtype)
            out.copy_to_host(buf, stream=stream)

        return buf[0]


    def __reduce(self, mem, gpu_mems, stream):
        from math import log, floor
        n = mem.shape[0]
        if n % 2 != 0: # odd?
            fatcut, thincut = mem.split(n - 1)
            # prevent freeing during async mode
            gpu_mems.append(fatcut)
            gpu_mems.append(thincut)
            # execute the kernel
            out = self.__reduce(fatcut, gpu_mems, stream)
            gpu_mems.append(out)
            return self(out, thincut, out=out, stream=stream)
        else: # even?
            left, right = mem.split(n / 2)
            # prevent freeing during async mode
            gpu_mems.append(left)
            gpu_mems.append(right)
            # execute the kernel
            self(left, right, out=left, stream=stream)
            if n / 2 > 1:
                return self.__reduce(left, gpu_mems, stream)
            else:
                return left

_re_signature = re.compile(r'\(\w+(?:,\w+)*\)')
_re_symbols = re.compile(r'\w+')

class CudaGUFuncDispatcher(CudaUFuncDispatcher):

    def __init__(self, types_to_retty_kernel, signature):
        super(CudaGUFuncDispatcher, self).__init__(types_to_retty_kernel)
        self._parse_signature(signature)

    def _parse_signature(self, signature):
        signature = ''.join(signature.split()) # remove whitespace
        inputs, outputs = signature.split('->')
        groups = _re_signature.findall(inputs)
        input_symbols = []
        for grp in groups:
            input_symbols.append(tuple(_re_symbols.findall(grp)))
        output_symbols = tuple(_re_symbols.findall(outputs))
        self.input_symbols = input_symbols
        self.output_symbols = output_symbols

    def _arguments_requirement(self, args):
        pass # TODO

    def _prepare_inputs(self, args):
        args = [np.ascontiguousarray(a) for a in args]
        return args

    def _adjust_dimension(self, broadcast_arrays):
        return broadcast_arrays # do nothing

    def _allocate_output(self, broadcast_arrays, result_dtype):
        shape = self._determine_output_shape(broadcast_arrays)
        return np.zeros(shape, broadcast_arrays[0].dtype)

    def _determine_output_shape(self, broadcast_arrays):
        # determine values of input shape symbols
        shapeholders = {}
        for ary, symbols in zip(broadcast_arrays, self.input_symbols):
            remain_shape = ary.shape[1:]    # ignore the first dimension
            for sym, val in zip(symbols, remain_shape):
                if sym in shapeholders and shapeholders[sym] != val:
                    raise ValueError("dimension %s mismatch: %d != %d",
                                     sym, val, shapeholders[sym])
                shapeholders[sym] = val
        # set values of output shape symbols
        innershape = tuple(shapeholders[sym] for sym in self.output_symbols)
        shape = (broadcast_arrays[0].shape[0],) + innershape
        return shape

    def _determine_element_count(self, broadcast_arrays):
        return broadcast_arrays[0].shape[0]


class CudaGeneralizedUFuncDispatcher(CudaUFuncDispatcher):
    """
    Implements a generalized CUDA function.
    """

    def __call__(self, ufunc, *args):
        raise
        ndim = 0
        core_ndim = 0

        assert ufunc.nin + ufunc.nout == len(args)

        args = [np.asarray(arg) for arg in args]

        # number of core dimensions per input
        core_dimensions = []
        for i, array in enumerate(args):
            core_dims = ufunc.core_num_dims[i]
            ndim = max(ndim, len(array.shape) - core_dims)
            core_ndim = max(core_ndim, core_dims)
            core_dimensions.append(core_dims)

        arrays = [np.asarray(a) for a in args]

def _apply_typemap(lfunctype):
    argtys = lfunctype.pointee.args
    def convert(ty):
        if isinstance(ty, _lc.IntegerType):
            return { 8: 'b',
                    16: 'h',
                    32: 'i',
                    64: 'l'}[ty.width]
        elif ty == _lc.Type.float():
            return 'f'
        elif ty == _lc.Type.double():
            return 'd'
        else:
            return '_'
    return ''.join(map(convert, argtys))

class CudaNumbaFuncDispatcher(object):

    def __init__(self, ptx_code, func_name, lfunctype):
        cu_module = _cuda.Module(ptx_code)
        self.ptx = ptx_code
        self.cu_function = _cuda.Function(cu_module, func_name)
        self.typemap = _apply_typemap(lfunctype)
        # default to prefer cache
        # self.cu_function.cache_config(prefer_shared=True)

    @property
    def device(self):
        return self.cu_function.device

    def _cast_args(self, args):
        # Cast scalar arguments to match the prototype.
        def convert(ty, val):
            if ty == 'f' or ty == 'd':
                return float(val)
            elif ty == 'i':
                return int(val)
            else:
                return val
        return [convert(ty, val) for ty, val in zip(self.typemap, args)]

    def __call__(self, args, griddim, blkdim, stream=0, sharedmem=0):
        args = self._cast_args(args)

        kernel_args = []

        retrievers = []
        def ndarray_gpu(x):
            dx, conv = cuda._auto_device(x, stream=stream)
            if conv:
                retrievers.append(lambda: dx.copy_to_host(x, stream=stream))
            return dx.as_cuda_arg()

        _typemapper = {'f': c_float,
                       'd': c_double,
                       'b': c_int8,
                       'h': c_int16,
                       'i': c_int32,
                       'l': c_int64,
                       '_': ndarray_gpu}

        for ty, arg in zip(self.typemap, args):
            arg = _typemapper[ty](arg)
            kernel_args.append(arg)

        cu_func = self.cu_function.configure(griddim, blkdim, stream=stream,
                                             sharedmem=sharedmem)

        cu_func(*kernel_args)

        for r in retrievers:
            r()
