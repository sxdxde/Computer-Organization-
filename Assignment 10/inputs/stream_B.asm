; B1
vshufps ymm0, ymm1, ymm2, 0x4E
vmulps ymm3, ymm0, ymm4
vfmadd231ps ymm5, ymm3, ymm6
vaddps ymm7, ymm5, ymm8
vshufps ymm9, ymm7, ymm10, 0xB1
vaddps ymm11, ymm9, ymm12
vmulps ymm13, ymm11, ymm14
vfmadd231ps ymm15, ymm13, ymm1
vaddps ymm2, ymm15, ymm4
vshufps ymm6, ymm2, ymm8, 0x1B
