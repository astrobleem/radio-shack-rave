/* PSG output and the presentation sound effects. Every byte to the SN76496
 * goes through psg(), which can also log it with the clock for captures.
 * Effects are one voice per channel with a linear attenuation decay, stepped
 * on BIOS ticks; channel 3 is the noise generator.
 */
static FILE *psg_log;
static void psg(unsigned value)
{
    DosSoundPsgByte(value);
    if(psg_log)fprintf(psg_log,"%lu %u\n",clk_fine(),value);
}
static void psg_mute_all(void)
{
    unsigned k;
    for(k=0;k<4;k++)psg(0x9f+(k<<5));
}
/* SN76496 divisors at 3.579545 MHz for MIDI 45..96. */
static const unsigned midi_div[52]={
 1017,960,906,855,807,762,719,679,641,605,571,539,508,480,453,428,404,381,
 360,339,320,302,285,269,254,240,226,214,202,190,180,170,160,151,143,135,
 127,120,113,107,101,95,90,85,80,76,71,67,64,60,57,53};
#define NOISE_WHITE(rate) (4|(rate))
typedef struct {
    unsigned long start;unsigned div;
    unsigned char att,rate,len,on,shown;
} Voice;
static Voice sfx_voice[4];
static int sfx_active;
/* Starts a voice now. For channel 3, `note` is the noise control value. */
static void sfx_note(unsigned ch,unsigned note,unsigned att,unsigned rate,unsigned len)
{
    Voice *v=&sfx_voice[ch];
    v->start=clk_ticks();v->att=(unsigned char)att;v->rate=(unsigned char)(rate?rate:1);
    v->len=(unsigned char)len;v->on=1;
    if(ch==3)psg(0xe0|note);
    else {
        v->div=midi_div[note<45?0:(note>96?51:note-45)];
        psg(0x80+(ch<<5)+(v->div&15));psg(v->div>>4);
    }
    psg(0x90+(ch<<5)+att);v->shown=(unsigned char)att;
    sfx_active=1;
}
static void sfx_step(void)
{
    unsigned ch,att;unsigned long age;Voice *v;
    if(!sfx_active)return;
    sfx_active=0;
    for(ch=0;ch<4;ch++) {
        v=&sfx_voice[ch];
        if(!v->on)continue;
        age=clk_ticks()-v->start;
        att=v->att+(unsigned)(age/v->rate);
        if(att>15 || age>=v->len){att=15;v->on=0;}
        else sfx_active=1;
        if(att!=v->shown){psg(0x90+(ch<<5)+att);v->shown=(unsigned char)att;}
    }
}
static void sfx_stop(void)
{
    unsigned ch;
    for(ch=0;ch<4;ch++)sfx_voice[ch].on=0;
    sfx_active=0;psg_mute_all();
}
static void sfx_chord(unsigned a,unsigned b,unsigned c,unsigned att,unsigned rate,unsigned len)
{
    sfx_note(0,a,att,rate,len);sfx_note(1,b,att,rate,len);sfx_note(2,c,att+1,rate,len);
}
static void sfx_blip(unsigned note){sfx_note(0,note,5,1,2);}
