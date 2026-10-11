#ifndef RAVE_SHIM_MALLOC_H
#define RAVE_SHIM_MALLOC_H
#include <stdlib.h>
#include <string.h>
#define _fmalloc malloc
#define _ffree free
#define _fmemset memset
#define _fmemcpy memcpy
#define _fmemmove memmove
#endif
