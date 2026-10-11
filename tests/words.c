#include <stdio.h>
#include <string.h>
#include "../src/FX.H"
int main(void){unsigned i,last=0,total=6*12*14,n,w,x;
 fx_judgment(0,0);
 for(i=0;i<24;i++){fx_judgment(2,i);if(fx_word<2||fx_word>7||fx_word==last)return 1;last=fx_word;}
 last=0;for(i=0;i<16;i++){fx_judgment(3,i);if(fx_word<8||fx_word>11||fx_word==last)return 2;last=fx_word;}
 fx_judgment(1,77);if(fx_word!=1||fx_kind!=1||fx_until!=89||fx_awesome!=24||fx_missed!=16)return 3;
 fx_judgment(0,99);if(fx_word||fx_great_cursor||fx_miss_cursor||fx_awesome||fx_missed)return 4;
 fx_judgment(2,100);if(strcmp(word_text[fx_word],"RAD!"))return 5;
 for(i=1;i<WORD_COUNT;i++){n=strlen(word_text[i]);w=(6*n-1)*2+4;x=(269-w/2)&~1;if(n>8||x<220||x+w>320)return 6;total+=((w+1)/2)*18;}
 if(total>9216)return 7;printf("PASS categories rotation reset timing counters bounds; cache=%u/9216\n",total);return 0;}
