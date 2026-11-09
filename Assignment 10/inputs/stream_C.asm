; C1: Chain 1
vaddps ymm0, ymm1, ymm2
vfmadd231ps ymm3, ymm0, ymm4
vaddps ymm5, ymm3, ymm6
vmulps ymm7, ymm5, ymm8
vaddps ymm9, ymm7, ymm10
vfmadd231ps ymm11, ymm9, ymm12
; C2: Chain 2
vmulps ymm13, ymm14, ymm15
vaddps ymm1, ymm13, ymm2
vshufps ymm4, ymm1, ymm5, 0x4E
vaddps ymm6, ymm4, ymm7
vfmadd231ps ymm8, ymm6, ymm9
vaddps ymm10, ymm8, ymm11
; C3: Independent operations
vaddps ymm12, ymm13, ymm14
vmulps ymm15, ymm1, ymm2
vshufps ymm3, ymm4, ymm5, 0xB1
vaddps ymm7, ymm8, ymm9
