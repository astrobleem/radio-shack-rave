/* Deterministic judgment core. Times are BIOS elapsed ticks, never frames. */
#define MAX_NOTES 512
#define WINDOW 3
#ifndef RAVE_JUDGMENT
#define RAVE_JUDGMENT(kind,now) ((void)0)
#endif
typedef struct {
    unsigned tick, end_tick, divisor;
    unsigned char lane, attenuation, note, reserved;
} Tap;
static Tap chart[MAX_NOTES];
static unsigned char judged[MAX_NOTES];
static unsigned taps, combo, best, hits, misses, ghosts;
static unsigned long score;
static unsigned lead_div,lead_att,lead_attacks,lead_releases;
static unsigned required_taps,lead_cursor,lead_owner,owner_seen;
static unsigned automatic_attacks,reference_attacks,automatic_skipped;
/* live_from: every chart index below it is judged or automatic, so the
   per-input and per-frame scans start there instead of at zero. */
static unsigned live_from,silent_hits;
static int reference_mode;
static int lead_until,flash_until[3];
static unsigned char flash_kind[3];
static void lead_cancel(int now)
{
    if(lead_div){lead_output(now,0,15);lead_releases++;}
    lead_div=0;lead_att=15;lead_until=-32767;
}
static void lead_step(int now)
{
    if(lead_div && now>=lead_until)lead_cancel(now);
}
static void lead_begin(unsigned index,int now,int player)
{
    lead_cancel(now);lead_owner=index;owner_seen=1;
    lead_until=player?now+(int)(chart[index].end_tick-chart[index].tick):
        (int)chart[index].end_tick;
    if(lead_until>(int)chart[index].end_tick)lead_until=chart[index].end_tick;
    lead_div=chart[index].divisor;lead_att=chart[index].attenuation;
    lead_output(now,lead_div,lead_att);lead_attacks++;
}
static void live_advance(void)
{
    while(live_from<taps && (chart[live_from].reserved || judged[live_from]))
        live_from++;
}
static void automatic_step(int now)
{
    unsigned i;
    if(now<0)return;
    while(lead_cursor<taps && chart[lead_cursor].tick<=(unsigned)now) {
        i=lead_cursor++;
        if((chart[i].reserved || reference_mode) && !judged[i]) {
            judged[i]=3;
            /* Do not burst expired tones or overwrite a newer early hit. */
            if(now>=(int)chart[i].end_tick || (owner_seen && i<lead_owner))
                automatic_skipped++;
            else {
                lead_begin(i,now,0);
                if(chart[i].reserved)automatic_attacks++;
                else reference_attacks++;
            }
        }
    }
}
static void reset_game(void)
{
    unsigned i;
    lead_cancel(-36);
    for(i=0;i<taps;i++)judged[i]=0;
    combo=best=hits=misses=ghosts=0; score=0;
    lead_attacks=lead_releases=0;
    lead_cursor=lead_owner=owner_seen=0;
    automatic_attacks=reference_attacks=automatic_skipped=0;
    live_from=silent_hits=0;
    RAVE_JUDGMENT(0,-36);
    for(i=0;i<3;i++){flash_until[i]=-32767;flash_kind[i]=0;}
    live_advance();
}
static void expire(int now)
{
    unsigned i;
    for(i=live_from;i<taps;i++) {
        if((int)chart[i].tick>now-WINDOW)break;
        if(!chart[i].reserved && !judged[i] && (int)chart[i].tick<now-WINDOW) {
            judged[i]=2; misses++; combo=0;
            RAVE_JUDGMENT(3,now);
            flash_until[chart[i].lane]=now+3;
            flash_kind[chart[i].lane]=2;
        }
    }
    live_advance();
}
static int hit(unsigned lane,int now)
{
    unsigned i, chosen=MAX_NOTES;
    int delta, nearest=WINDOW+1;
    if(reference_mode){ghosts++;return 0;}
    for(i=live_from;i<taps;i++) {
        if((int)chart[i].tick>now+WINDOW)break;
        delta=(int)chart[i].tick-now;
        if(delta<0)delta=-delta;
        if(!chart[i].reserved && !judged[i] &&
           (unsigned)chart[i].lane==lane && delta<nearest) {
            chosen=i; nearest=delta;
        }
    }
    if(chosen==MAX_NOTES){ghosts++;return 0;}
    judged[chosen]=1; hits++; combo++;
    /* Judgment always uses the full +/-WINDOW. The tone is a separate
       question: early hits sound immediately for their authored length,
       ending no later than the authored off. A late hit sounds only for the
       time remaining and never takes the lead back from a newer note. */
    if((!owner_seen || chosen>=lead_owner) && now<(int)chart[chosen].end_tick)
        lead_begin(chosen,now,1);
    else silent_hits++;
    flash_until[lane]=now+3;flash_kind[lane]=1;
    if(combo>best)best=combo;
    score+=(unsigned)(nearest<=1?100:60);
    score+=(unsigned)(combo<50?combo:50);
    RAVE_JUDGMENT(nearest<=1?2:1,now);
    live_advance();
    return 1;
}
