v {xschem version=3.4.8RC file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {CMOS inverter, IHP SG13G2 (sg13_lv 1.2 V devices)} 40 -260 0 0 0.4 0.4 {}
T {PMOS W/L = 2/0.13 um, NMOS W/L = 1/0.13 um} 40 -225 0 0 0.3 0.3 {}
N 220 -130 220 -180 {lab=VDD}
N 120 -180 220 -180 {lab=VDD}
N 220 -100 260 -100 {lab=VDD}
N 220 -70 220 0 {lab=OUT}
N 220 0 220 70 {lab=OUT}
N 220 0 320 0 {lab=OUT}
N 220 130 220 180 {lab=VSS}
N 120 180 220 180 {lab=VSS}
N 220 100 260 100 {lab=VSS}
N 80 0 140 0 {lab=IN}
N 140 -100 140 0 {lab=IN}
N 140 0 140 100 {lab=IN}
N 140 -100 180 -100 {lab=IN}
N 140 100 180 100 {lab=IN}
C {devices/ipin.sym} 80 0 0 0 {name=p1 lab=IN}
C {devices/opin.sym} 320 0 0 0 {name=p2 lab=OUT}
C {devices/iopin.sym} 120 -180 0 1 {name=p3 lab=VDD}
C {devices/iopin.sym} 120 180 0 1 {name=p4 lab=VSS}
C {sg13g2_pr/sg13_lv_pmos.sym} 200 -100 0 0 {name=M1
l=0.13u
w=2u
ng=1
m=1
model=sg13_lv_pmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 200 100 0 0 {name=M2
l=0.13u
w=1u
ng=1
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {devices/lab_pin.sym} 260 -100 0 1 {name=p5 sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 260 100 0 1 {name=p6 sig_type=std_logic lab=VSS}
