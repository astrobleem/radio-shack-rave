/* Installed host Watcom: read little-endian RBG2, exercise exact game core. */
#include <stdio.h>
#include <string.h>
static unsigned events;
static void lead_output(int now,unsigned divisor,unsigned attenuation)
{ events++;printf("L %d %u %u\n",now,divisor,attenuation); }
#include "../src/CORE.H"
static unsigned word(FILE *f)
{ unsigned lo=getc(f),hi=getc(f);return lo|(hi<<8); }
int main(int argc,char **argv)
{
    FILE *f;char magic[4];unsigned ver,end,ns,i;int now,play;
    if(argc!=3)return 2;play=!strcmp(argv[2],"hit");reference_mode=!strcmp(argv[2],"ref");
    f=fopen(argv[1],"rb");if(!f)return 2;
    fread(magic,1,4,f);ver=word(f);end=word(f);ns=word(f);taps=word(f);
    if(memcmp(magic,"RBG3",4)||ver!=3||taps>MAX_NOTES){fclose(f);return 2;}
    fseek(f,12L+12L*ns,SEEK_SET);
    for(i=0;i<taps;i++) {
        chart[i].tick=word(f);chart[i].end_tick=word(f);chart[i].divisor=word(f);
        chart[i].lane=getc(f);chart[i].attenuation=getc(f);
        chart[i].note=getc(f);chart[i].reserved=getc(f);
    }
    fclose(f);required_taps=0;for(i=0;i<taps;i++)if(!chart[i].reserved)required_taps++;reset_game();events=0;
    for(now=-3;now<=(int)end+4;now++) {
        lead_step(now);automatic_step(now);expire(now);
        if(play)for(i=0;i<taps;i++)if(!chart[i].reserved && (int)chart[i].tick==now)hit(chart[i].lane,now);
    }
    fprintf(stderr,"hits=%u misses=%u attacks=%u releases=%u events=%u\n",hits,misses,lead_attacks,lead_releases,events);
    return lead_div || (reference_mode?events!=taps*2:(play?(hits!=required_taps||events!=taps*2):(misses!=required_taps||automatic_attacks!=taps-required_taps)));
}

