#include <stdio.h>
static unsigned events;
static void lead_output(int t,unsigned d,unsigned a){events++;}
#include "../src/CORE.H"
int main(void)
{
 unsigned i;int now,bad=0;
 taps=3;required_taps=2;
 for(i=0;i<taps;i++){
  chart[i].tick=10+i*6;chart[i].end_tick=14+i*6;
  chart[i].divisor=400+i*20;chart[i].attenuation=3;chart[i].lane=i;
  chart[i].reserved=i==1;
 }
 reset_game();events=0;
 for(now=0;now<30;now++) {
  lead_step(now);automatic_step(now);expire(now);
  if(now==10)hit(0,now);
 }
 if(hits!=1||misses!=1||automatic_attacks!=1||lead_attacks!=2||events!=4)bad++;
 reset_game();events=0;
 hit(2,19);automatic_step(19);
 if(lead_owner!=2||lead_div!=440||automatic_skipped!=1||events!=1)bad++;
 for(i=0;i<1000;i++)hit(2,19);
 if(events!=1)bad++;
 reset_game();if(lead_div||events!=2)bad++;
 reset_game();events=0;automatic_step(30);
 if(lead_div||events||automatic_skipped!=1)bad++;
 reference_mode=1;reset_game();events=0;
 for(now=0;now<30;now++){lead_step(now);automatic_step(now);expire(now);}
 if(events!=6||misses||hits||reference_attacks!=2||automatic_attacks!=1)bad++;
 /* Late window: a short required note followed by an automatic note keeps
    the full +/-WINDOW judgment; the late tone is simply not replayed. */
 reference_mode=0;taps=2;
 chart[0].tick=10;chart[0].end_tick=12;chart[0].lane=0;chart[0].reserved=0;
 chart[1].tick=12;chart[1].end_tick=14;chart[1].lane=1;chart[1].reserved=1;
 for(i=0;i<=3;i++) {
  reset_game();events=0;
  for(now=0;now<20;now++){lead_step(now);automatic_step(now);
   if(now==10+(int)i && !hit(0,now))bad++;
   expire(now);}
  if(hits!=1||misses||ghosts||silent_hits!=(i>=2))bad++;
 }
 /* An early press on a later lane no longer cancels an older note's window. */
 taps=2;chart[1].reserved=0;chart[1].tick=14;chart[1].end_tick=18;
 reset_game();events=0;
 if(!hit(1,12)||!hit(0,12)||hits!=2||silent_hits!=1||lead_owner!=1)bad++;
 printf("automatic/manual/early-owner/1000repeat/reset/catchup/reference/late-window: %s\n",bad?"FAIL":"PASS");
 return bad;
}
