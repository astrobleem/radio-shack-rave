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
 printf("automatic/manual/early-owner/1000repeat/reset/catchup/reference: %s\n",bad?"FAIL":"PASS");
 return bad;
}
