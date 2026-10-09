/* Display-only judgment mailbox. It never reads or changes game decisions. */
#include "WORDS.H"
static unsigned fx_kind,fx_seen,fx_changes,fx_shown;
static unsigned fx_awesome,fx_nice,fx_missed;
static int fx_until,fx_slow_until,fx_start;
static void fx_judgment(unsigned kind,int now)
{
    words_choose(kind);
    fx_kind=kind;fx_until=kind?now+12:-32767;fx_start=now;
    if(!kind){fx_seen=fx_changes=fx_shown=0;fx_slow_until=-32767;
        fx_awesome=fx_nice=fx_missed=0;}
    else {
        fx_seen++;
        if(kind==2)fx_awesome++;
        else if(kind==1)fx_nice++;
        else fx_missed++;
    }
}
#define RAVE_JUDGMENT(kind,now) fx_judgment(kind,now)
