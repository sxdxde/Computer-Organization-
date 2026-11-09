; A1
vaddps ymm0, ymm1, ymm2
vfmadd231ps ymm3, ymm0, ymm4
vaddps ymm5, ymm3, ymm6
vmulps ymm7, ymm5, ymm8
vaddps ymm9, ymm7, ymm10
vshufps ymm11, ymm9, ymm12, 0x4E
vmulps ymm13, ymm11, ymm14
vaddps ymm15, ymm13, ymm1
vfmadd231ps ymm2, ymm15, ymm4
vaddps ymm6, ymm2, ymm8
