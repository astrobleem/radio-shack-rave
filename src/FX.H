/* Display-only judgment mailbox. It never reads or changes game decisions. */
static unsigned fx_kind,fx_seen,fx_changes,fx_shown;
static int fx_until,fx_slow_until;
static void fx_judgment(unsigned kind,int now)
{
    fx_kind=kind;fx_until=kind?now+12:-32767;
    if(!kind){fx_seen=fx_changes=fx_shown=0;fx_slow_until=-32767;}
    else fx_seen++;
}
#define RAVE_JUDGMENT(kind,now) fx_judgment(kind,now)
