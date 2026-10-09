/* Bounded DOS 8.3 catalog; its PRNG never touches gameplay randomness. */
#define SONG_MAX 64
#define SONG_SCAN_MAX 1024
static char song_names[SONG_MAX][13];
static unsigned char song_bag[SONG_MAX], song_ok[SONG_MAX];
static unsigned song_count, song_pos, song_last=SONG_MAX;
static unsigned long song_rng=1;

static int song_name_ok(const char *s)
{
    unsigned n=0;int c;
    while(*s && *s!='.') {
        c=(unsigned char)*s++;
        if(++n>8 || !((c>='A' && c<='Z') || (c>='a' && c<='z') ||
           (c>='0' && c<='9') || strchr("_$~!#%&-{}()@'`",c)))return 0;
    }
    return n && strlen(s)==4 && *s=='.' && (s[1]=='R' || s[1]=='r') &&
        (s[2]=='B' || s[2]=='b') && (s[3]=='G' || s[3]=='g') && !s[4];
}
static void song_path(char *path,const char *name)
{
    strcpy(path,"SONGS\\");strcat(path,name);
}
static void songs_reset(unsigned long seed)
{
    song_count=song_pos=0;song_last=SONG_MAX;
    song_rng=seed&65535UL;
    memset(song_ok,0,sizeof(song_ok));
}
static int songs_add(const char *name)
{
    unsigned i;
    if(song_count==SONG_MAX || !song_name_ok(name))return 0;
    for(i=0;i<song_count;i++)if(!strcmp(name,song_names[i]))return 0;
    /* Directory discovery reads names only. Validate when selected. */
    strcpy(song_names[song_count],name);song_ok[song_count++]=1;
    song_pos=song_count;return 1;
}
static unsigned song_random(unsigned bound)
{
    song_rng=(song_rng*25173UL+13849UL)&65535UL;
    return (unsigned)(song_rng%bound);
}
static void songs_shuffle(void)
{
    unsigned i,j;unsigned char tmp;
    for(i=0;i<song_count;i++)song_bag[i]=(unsigned char)i;
    for(i=song_count;i>1;i--) {
        j=song_random(i);tmp=song_bag[i-1];
        song_bag[i-1]=song_bag[j];song_bag[j]=tmp;
    }
    /* Skip disabled files when protecting the boundary between bags. */
    for(i=0;i<song_count;i++)if(song_ok[song_bag[i]])break;
    if(i<song_count && song_bag[i]==song_last) {
        for(j=i+1;j<song_count;j++)if(song_ok[song_bag[j]]) {
            tmp=song_bag[i];song_bag[i]=song_bag[j];song_bag[j]=tmp;break;
        }
    }
    song_pos=0;
}
static int songs_next(int (*load)(const char *))
{
    unsigned tries,id,j;unsigned char tmp;char path[19];
    /* A partial bag plus one complete bag is enough even after removals. */
    for(tries=0;tries<song_count*2;tries++) {
        if(song_pos>=song_count)songs_shuffle();
        id=song_bag[song_pos++];
        if(!song_ok[id])continue;
        /* Lazy validation can disable entries before the first playable one.
           Defer the previous song while any other untried candidate remains. */
        if(id==song_last)for(j=song_pos;j<song_count;j++)
            if(song_ok[song_bag[j]] && song_bag[j]!=song_last) {
                tmp=song_bag[song_pos-1];song_bag[song_pos-1]=song_bag[j];
                song_bag[j]=tmp;id=song_bag[song_pos-1];break;
            }
        song_path(path,song_names[id]);
        if(load(path)){song_last=id;return 1;}
        song_ok[id]=0;
    }
    return 0;
}
static void songs_discover(void)
{
    struct find_t found;unsigned scanned=0;
    if(_dos_findfirst("SONGS\\*.RBG",_A_NORMAL,&found))return;
    do {
        if(!(found.attrib&(_A_SUBDIR|_A_VOLID)))songs_add(found.name);
        scanned++;
        if(song_count==SONG_MAX || scanned==SONG_SCAN_MAX)break;
    } while(!_dos_findnext(&found));
}
