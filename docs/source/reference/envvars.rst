
Environment variables
=====================

Numba allows its behaviour to be changed by using environment variables.
Unless otherwise mentioned, those variables have integer values and
default to zero.


Errors and warnings display
---------------------------

.. envvar:: NUMBA_WARNINGS

   If set to non-zero, printout of Numba warnings is enabled, otherwise
   the warnings are suppressed.  The warnings can give insight into the
   compilation process.


Debugging
---------

These variables influence what is printed out during compilation of
:term:`JIT functions <JIT function>`.

.. envvar:: NUMBA_DEBUG

   If set to non-zero, print out all possible debugging information during
   function compilation.  Finer-grained control can be obtained using other
   variables below.

.. envvar:: NUMBA_DEBUG_FRONTEND

   If set to non-zero, print out debugging information during operation
   of the compiler frontend, up to and including generation of the Numba
   Intermediate Representation.

.. envvar:: NUMBA_DUMP_BYTECODE

   If set to non-zero, print out the Python :py:term:`bytecode` of
   compiled functions.

.. envvar:: NUMBA_DUMP_CFG

   If set to non-zero, print out information about the Control Flow Graph
   of compiled functions.

.. envvar:: NUMBA_DUMP_IR

   If set to non-zero, print out the Numba Intermediate Representation
   of compiled functions.

.. envvar:: NUMBA_DUMP_ANNOTATION

   If set to non-zero, print out types annotations for compiled functions.

.. envvar:: NUMBA_DUMP_LLVM

   Dump the unoptimized LLVM assembler source of compiled functions.
   Unoptimized code is usually very verbose; therefore,
   :envvar:`NUMBA_DUMP_OPTIMIZED` is recommended instead.

.. envvar:: NUMBA_DUMP_FUNC_OPT

   Dump the LLVM assembler source after the LLVM "function optimization"
   pass, but before the "module optimization" pass.  This is useful mostly
   when developing Numba itself, otherwise use :envvar:`NUMBA_DUMP_OPTIMIZED`.

.. envvar:: NUMBA_DUMP_OPTIMIZED

   Dump the LLVM assembler source of compiled functions after all
   optimization passes.  The output includes the raw function as well as
   its CPython-compatible wrapper (whose name begins with ``wrapper.``).
   Note that the function is often inlined inside the wrapper, as well.

.. envvar:: NUMBA_DUMP_ASSEMBLY

   Dump the native assembler code of compiled functions.

.. seealso::
   :ref:`troubleshooting` and :ref:`architecture`.


Compilation options
-------------------

.. envvar:: NUMBA_OPT

   The optimization level; this option is passed straight to LLVM.

   *Default value:* 3

.. envvar:: NUMBA_LOOP_VECTORIZE

   If set to non-zero, enable LLVM loop vectorization.

   *Default value:* 1 (except on 32-bit Windows)

.. envvar:: NUMBA_ENABLE_AVX

   If set to non-zero, enable AVX optimizations in LLVM.  This is disabled
   by default as it can pessimize generated code.

.. envvar:: NUMBA_COMPATIBILITY_MODE

   If set to non-zero, compilation of JIT functions will never entirely
   fail, but instead generate a fallback that simply interprets the
   function.  This is only to be used if you are migrating a large
   codebase from an old Numba version (before 0.12), and want to avoid
   breaking everything at once.  Otherwise, please don't use this.


GPU support
-----------

.. envvar:: NUMBA_DISABLE_CUDA

   If set to non-zero, disable CUDA support.

.. envvar:: NUMBA_FORCE_CUDA_CC

   If set, force the CUDA compute capability to the given version (a
   string of the type ``major.minor``), regardless of attached devices.