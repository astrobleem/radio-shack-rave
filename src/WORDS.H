/* Display words only; category and timing remain owned by the judgment core. */
#define WORD_COUNT 12
static const char *word_text[WORD_COUNT]={"","NICE!","RAD!","SWEET!","STELLAR!","NAILED!","RIGHTON!","WICKED!","OOPS!","WHIFF!","WHOOPS!","AGAIN!"};
static unsigned fx_word,fx_great_cursor,fx_miss_cursor;
static void words_reset(void){fx_word=fx_great_cursor=fx_miss_cursor=0;}
static void words_choose(unsigned kind)
{
 if(kind==1)fx_word=1;
 else if(kind==2){fx_word=2+fx_great_cursor;if(++fx_great_cursor==6)fx_great_cursor=0;}
 else if(kind==3){fx_word=8+fx_miss_cursor;if(++fx_miss_cursor==4)fx_miss_cursor=0;}
 else words_reset();
}
