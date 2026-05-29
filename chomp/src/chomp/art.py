"""art.py — chomp easter egg: Chain Chomp kaomoji + ANSI ASCII art."""

# (( ゜◇゜)  — the "Crystal Chomper": a bit being chomped.
KAOMOJI = "(( ゜◇゜)"

# ANSI-colored Chain Chomp (from chomp.txt). ESC sequences embedded; print as-is.
ART = (
    '\x1b[90m                                                                                \x1b[34mv>>>>><\\)\x1b[90m))||"//+==^;;,,                \x1b[39m\n'
    "\x1b[90m                                                                            \x1b[34m)vvvivvvi)>><\x1b[90m\\))|\"//++=^^;,:'_`.            \x1b[39m\n"
    '\x1b[90m                                                                         \x1b[34m%%xxxccxx%%vi)>\x1b[90m<\\)||"//+=^^;,:;)c**x;          \x1b[39m\n'
    '\x1b[90m                                                                      \x1b[34m)lllsrs}?!Is%vvi)>\x1b[90m<\\)||"/++=;;+%t\x1b[34mw\x1b[37mmVV5F\x1b[34mf\x1b[37m4\x1b[90m         \x1b[39m\n'
    '\x1b[90m                                                                    \x1b[34m)s{}??7\x1b[36m5\x1b[37mVE4gkG6\x1b[90m1>\x1b[34mv)\x1b[90m><\\)|"//+^=)1\x1b[35mf\x1b[37mg4EEEEh\x1b[90mJ\x1b[31mf\x1b[37mpgg\x1b[90m       \x1b[39m\n'
    '\x1b[90m                                                                   \x1b[34m{*!ten\x1b[37mPO4X\x1b[90mz::)\x1b[37mVOg\x1b[90m{"\x1b[34mi\x1b[90m><\\)|"/="lL\x1b[37mpV4444EEEgq\x1b[90mjT\x1b[33my\x1b[37mFqd\x1b[90m     \x1b[39m\n'
    '\x1b[90m                                                                 \x1b[34ms*!ouJ\x1b[36m6\x1b[37mWY\x1b[90m;lC}\\;,\x1b[37mgbh\x1b[90m%+i>\\)|"+|sL\x1b[37mph44444EEEEEgq\x1b[90mT#\x1b[31mw\x1b[37m556Q\x1b[90m   \x1b[39m\n'
    '\x1b[90m                                                                \x1b[34ml}tu\x1b[36my6S\x1b[37m8QP\x1b[90m/:/\\%t\x1b[37m4Z5\x1b[90ml=i)>\\)"|*\x1b[34mf\x1b[90m!<r1L\x1b[31mf\x1b[37mpgd444EEEXEp523F32Q\x1b[90m \x1b[39m\n'
    "\x1b[90m                                                               \x1b[34mrIeT\x1b[36mF\x1b[37m4AHZK0HbXPZE\x1b[34mw\x1b[90m}|)xv)<)){J\x1b[37mgg\x1b[90m?`--_;|x!z\x1b[31mf\x1b[37mmgVdEEE\x1b[90m  \x1b[37mgp3y3\x1b[90m \x1b[39m\n"
    "\x1b[90m                                                               \x1b[34m*tn\x1b[36m5\x1b[37m48RQMbVqp\x1b[34mwj\x1b[90m!l%x\x1b[34msr\x1b[90mxi<)cn\x1b[37mSddX\x1b[90mo`--___'\x1b[31m'\x1b[90m/o\x1b[31mwf\x1b[37m3FphgQ\x1b[90m    w\x1b[37mQ\x1b[90m \x1b[39m\n"
    "\x1b[90m                                                              \x1b[34m{!7C\x1b[36mm\x1b[37mPK0QQQ0$g\x1b[36mp\x1b[34mwue1I{\x1b[90mcv>ve\x1b[37mp4EEEP\x1b[90mT`--__'\x1b[31m'\x1b[90m,lCJC\x1b[31mC\x1b[33my\x1b[31mw\x1b[37m55\x1b[90m        \x1b[39m\n"
    "\x1b[90m                                                              \x1b[34m*[jC\x1b[36mF\x1b[37mVY$DBH&PS\x1b[36m3\x1b[34mT71?{\x1b[90ml%v]\x1b[37m54XXPXXG5\x1b[90m--__':/i                 \x1b[39m\n"
    "\x1b[90m                                                            J\x1b[34mC?!ouC\x1b[36m2m\x1b[37mhdVg\x1b[36mp3\x1b[34mJje[I{l\x1b[90m%|i1L#w\x1b[37m35pmh\x1b[33m3\x1b[90m_-__':>T\x1b[37mVXggp\x1b[90m            \x1b[39m\n"
    "\x1b[90m                                          \x1b[37m8\x1b[90mI               uC\x1b[37m3\x1b[34mI?1ezLT#J#nL7a[?*s\x1b[90mc)+-   ...`_';,`--___',v\x1b[31mT\x1b[37mXOV5\x1b[90m     \x1b[37mObp\x1b[90mw  \x1b[39m\n"
    "\x1b[90m                                 .\x1b[37mQWkXVm5\x1b[90mw\x1b[37m33\x1b[90m*i             #\x1b[37m2p\x1b[34m?}!][1tttt1]?}*sl\x1b[90mx)'      ......```--__''\x1b[31m':\x1b[90m<\x1b[31mn\x1b[37mGV\x1b[90m  \x1b[37mXbYOb2\x1b[90mn  \x1b[39m\n"
    "\x1b[90m                               \x1b[37mKGm3\x1b[90mJLe1Io\x1b[36my\x1b[90m*?tv%       \x1b[37mBgdqqmmq\x1b[34mos}I}}}}}}*{rlc\x1b[90mx%|\\}!?}*{c' ....```--____,\x1b[31m::,\x1b[90mi\x1b[31mT\x1b[37mhOZkOOh\x1b[33m3\x1b[37mVdX\x1b[39m\n"
    "\x1b[90m                               \x1b[37mV\x1b[90mJ?<+    \x1b[37mP4\x1b[90mJ{rx>%\x1b[37mS\x1b[90m   \x1b[37m0G\x1b[36my\x1b[90mn\x1b[37m3\x1b[90mCa[n#7\x1b[34mrr{{rrrrlccx%\x1b[90mv)>\\)va\x1b[37mF4Gbb\x1b[31mf\x1b[90m+ ...`````-^cj\x1b[37mq\x1b[31mJ,,;;}\x1b[37m4&YYZpq4A8\x1b[39m\n"
    "\x1b[90m                              \x1b[37mQky\x1b[90ms%vl!T#nzto?l<)>%\x1b[37mm4\x1b[34mC\x1b[90m}<x)lj[rlsl\x1b[34mlxccxx%%%vi\x1b[90m)><\\)|/=/xz\x1b[37mmPbm\x1b[90m) ....`+rn\x1b[37mhbOAU\x1b[31m?:;^^)\x1b[35my\x1b[37mOY4SGHK\x1b[90m \x1b[39m\n"
    '\x1b[90m                 \x1b[37mK\x1b[90m#?I*{      \x1b[37mQV\x1b[90mevv%xxclv\\- 1[*l%x?Ix"  \x1b[37mQRE\x1b[90mLlv<)i\x1b[34m%%vvvvvi)\x1b[90m>>\\\\)|"//+=;,+xz\x1b[37mmh\x1b[90m?-`/*#\x1b[37mgGkkOA&$P\x1b[31m+,;=++\x1b[35my\x1b[37mhhAW@8\x1b[90m \x1b[39m\n'
    "\x1b[90m                \x1b[37mq\x1b[90mn{x%llllx>\x1b[37mSg\x1b[90mucir            Irxcx>)<I\x1b[37m3g\x1b[90mnr<+    \x1b[34mvii))))>\x1b[90m<\\\\)||\"/++=^^;,''^vtIL\x1b[37mSXPGZbkA&8$H\x1b[31mo,;^>e\x1b[37m5GKWK$\x1b[90m  \x1b[39m\n"
    '\x1b[90m  \x1b[37mQQ\x1b[90m          `\x1b[37mm\x1b[90mesuc"\\rss}LT*iii               o{lrv%??r\\        \x1b[34m)>>><\x1b[90m<\\\\)||"//++=^^;;,,,,:\'^\\ro\x1b[36my\x1b[37mhPkA&U$@HP\x1b[31m=/!w\x1b[37md$BWZP\x1b[90m   \x1b[39m\n'
    '\x1b[37mAg\x1b[90mTuLzoat1[?swL!n\x1b[37mq\x1b[90mL%>)|+:e?i%ixi                \x1b[37m5\x1b[90m[?*sc)            \x1b[34m\\\\\\\\\x1b[90m))|""//++=^^;;,,,;;;;;;,,;|x1\x1b[34mJ\x1b[37mmXO$HD\x1b[31mJ\x1b[90mu\x1b[37mq&NWK\x1b[36mp\x1b[90m)    \x1b[39m\n'
    '\x1b[90mCl+)%ls{*}I?]eoutc|vvvvi)>\\>lx%                    x|               \\)|||"//++==^^;;;;;;;;;^^^^==^^;^+)v*\x1b[34mtLj\x1b[90mt\x1b[36my5\x1b[34mwL\x1b[90m*^\x1b[34m.\x1b[90m    \x1b[39m\n'
    '\x1b[90mjl>%crs}*l\x1b[37mXp\x1b[90mTz{>^       {{lclc                                        \x1b[34m+\x1b[90m""///++=^^;;;;;;^^^^^==++++//""\x1b[34m""////"/+^:.\x1b[90m      \x1b[39m\n'
    '\x1b[90mz!{rs{*}}I1ac)<                                                          //++==^^^^^^^^===+++///"\x1b[34m"||))\\\\\\\\\\))||>\x1b[90m        \x1b[39m\n'
    '\x1b[90m       )<iv)%%                                                              =====+++++////""\x1b[34m||))\\\\<<>><<\\\\))\x1b[90m|           \x1b[39m\n'
    '\x1b[90m                                                                                /\x1b[34m/\x1b[90m///""\x1b[34m||))\\\\<<>>>>>>>>>\x1b[90m%               \x1b[39m\n'
)


def chomp(stream=None) -> None:
    """Print the Chain Chomp kaomoji + ASCII art."""
    import sys

    out = stream or sys.stdout
    out.write(KAOMOJI + "  chomp chomp!\n\n")
    out.write(ART + "\n")
