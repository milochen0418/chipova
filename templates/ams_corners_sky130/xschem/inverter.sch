v {xschem version=3.4.8RC file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {CMOS inverter, SkyWater SKY130 (sky130_fd_pr 1.8 V devices)} 40 -260 0 0 0.4 0.4 {}
T {PMOS W/L = 2/0.15 um, NMOS W/L = 1/0.15 um} 40 -225 0 0 0.3 0.3 {}
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
C {sky130_fd_pr/pfet_01v8.sym} 200 -100 0 0 {name=M1
L=0.15
W=2
nf=1
mult=1
ad="'int((nf+1)/2) * W/nf * 0.29'"
pd="'2*int((nf+1)/2) * (W/nf + 0.29)'"
as="'int((nf+2)/2) * W/nf * 0.29'"
ps="'2*int((nf+2)/2) * (W/nf + 0.29)'"
nrd="'0.29 / W'" nrs="'0.29 / W'"
sa=0 sb=0 sd=0
model=pfet_01v8
spiceprefix=X
}
C {sky130_fd_pr/nfet_01v8.sym} 200 100 0 0 {name=M2
L=0.15
W=1
nf=1
mult=1
ad="'int((nf+1)/2) * W/nf * 0.29'"
pd="'2*int((nf+1)/2) * (W/nf + 0.29)'"
as="'int((nf+2)/2) * W/nf * 0.29'"
ps="'2*int((nf+2)/2) * (W/nf + 0.29)'"
nrd="'0.29 / W'" nrs="'0.29 / W'"
sa=0 sb=0 sd=0
model=nfet_01v8
spiceprefix=X
}
C {devices/lab_pin.sym} 260 -100 0 1 {name=p5 sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 260 100 0 1 {name=p6 sig_type=std_logic lab=VSS}
