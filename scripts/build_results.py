"""Build data/results_actual.csv — all 104 match results, WC 2026.
Sources: Yahoo Sports tournament archive, FIFA official match centre, worldcupmatchtime.com
"""
import csv

GROUP = """A|Mexico|2|South Africa|0
A|South Korea|2|Czechia|1
A|Czechia|1|South Africa|1
A|Mexico|1|South Korea|0
A|Mexico|3|Czechia|0
A|South Africa|1|South Korea|0
B|Canada|1|Bosnia|1
B|Switzerland|1|Qatar|1
B|Switzerland|4|Bosnia|1
B|Canada|6|Qatar|0
B|Switzerland|3|Canada|1
B|Bosnia|3|Qatar|1
C|Brazil|1|Morocco|1
C|Scotland|1|Haiti|0
C|Scotland|0|Morocco|1
C|Brazil|3|Haiti|0
C|Scotland|0|Brazil|3
C|Morocco|4|Haiti|2
D|USA|4|Paraguay|1
D|Australia|2|Turkiye|0
D|USA|2|Australia|0
D|Turkiye|0|Paraguay|1
D|Turkiye|3|USA|2
D|Paraguay|0|Australia|0
E|Germany|7|Curacao|1
E|Ivory Coast|1|Ecuador|0
E|Germany|2|Ivory Coast|1
E|Ecuador|0|Curacao|0
E|Curacao|0|Ivory Coast|2
E|Ecuador|2|Germany|1
F|Netherlands|2|Japan|2
F|Sweden|5|Tunisia|1
F|Netherlands|5|Sweden|1
F|Japan|4|Tunisia|0
F|Japan|1|Sweden|1
F|Netherlands|3|Tunisia|1
G|Belgium|1|Egypt|1
G|Iran|2|New Zealand|2
G|Belgium|0|Iran|0
G|Egypt|3|New Zealand|1
G|Egypt|1|Iran|1
G|Belgium|5|New Zealand|1
H|Spain|0|Cape Verde|0
H|Saudi Arabia|1|Uruguay|1
H|Spain|4|Saudi Arabia|0
H|Uruguay|2|Cape Verde|2
H|Cape Verde|0|Saudi Arabia|0
H|Spain|1|Uruguay|0
I|France|3|Senegal|1
I|Norway|4|Iraq|1
I|France|3|Iraq|0
I|Norway|3|Senegal|2
I|France|4|Norway|1
I|Senegal|5|Iraq|0
J|Argentina|3|Algeria|0
J|Austria|3|Jordan|1
J|Argentina|2|Austria|0
J|Jordan|1|Algeria|2
J|Argentina|3|Jordan|1
J|Austria|3|Algeria|3
K|Portugal|1|DR Congo|1
K|Uzbekistan|1|Colombia|3
K|Portugal|5|Uzbekistan|0
K|Colombia|1|DR Congo|0
K|Colombia|0|Portugal|0
K|DR Congo|3|Uzbekistan|1
L|England|4|Croatia|2
L|Ghana|1|Panama|0
L|England|0|Ghana|0
L|Panama|0|Croatia|1
L|England|2|Panama|0
L|Croatia|2|Ghana|1"""

# stage|teamA|gA|teamB|gB|extra (pens as "p4-3", aet flag)
KO = """R32|Canada|1|South Africa|0|
R32|Brazil|2|Japan|1|
R32|Germany|1|Paraguay|1|PAR 4-3 pens
R32|Netherlands|1|Morocco|1|MAR 3-2 pens
R32|Norway|2|Ivory Coast|1|
R32|France|3|Sweden|0|
R32|Mexico|2|Ecuador|0|
R32|England|2|DR Congo|1|
R32|Belgium|3|Senegal|2|aet
R32|USA|2|Bosnia|0|
R32|Spain|3|Austria|0|
R32|Portugal|2|Croatia|1|
R32|Switzerland|2|Algeria|0|
R32|Egypt|1|Australia|1|EGY 4-2 pens
R32|Argentina|3|Cape Verde|2|aet
R32|Colombia|1|Ghana|0|
R16|Morocco|3|Canada|0|
R16|France|1|Paraguay|0|
R16|Norway|2|Brazil|1|
R16|England|3|Mexico|2|
R16|Spain|1|Portugal|0|
R16|Belgium|4|USA|1|
R16|Argentina|3|Egypt|2|
R16|Switzerland|0|Colombia|0|SUI 4-3 pens
QF|France|2|Morocco|0|
QF|Spain|2|Belgium|1|
QF|England|2|Norway|1|aet
QF|Argentina|3|Switzerland|1|aet
SF|Spain|2|France|0|
SF|Argentina|2|England|1|
3RD|England|6|France|4|
FINAL|Spain|1|Argentina|0|aet"""

CANON = {"Bosnia": "Bosnia & Herzegovina", "Curacao": "Curaçao", "Turkiye": "Türkiye"}


def canon(t):
    return CANON.get(t, t)


rows = []
for ln in GROUP.strip().splitlines():
    g, a, ga, b, gb = ln.split("|")
    rows.append({"stage": "GROUP", "group": g, "team_a": canon(a), "goals_a": ga,
                 "team_b": canon(b), "goals_b": gb, "notes": ""})
for ln in KO.strip().splitlines():
    st, a, ga, b, gb, note = ln.split("|")
    rows.append({"stage": st, "group": "", "team_a": canon(a), "goals_a": ga,
                 "team_b": canon(b), "goals_b": gb, "notes": note})

with open("data/results_actual.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["stage", "group", "team_a", "goals_a", "team_b", "goals_b", "notes"])
    w.writeheader()
    w.writerows(rows)

print(f"wrote {len(rows)} matches ({sum(1 for r in rows if r['stage']=='GROUP')} group + "
      f"{sum(1 for r in rows if r['stage']!='GROUP')} knockout)")
