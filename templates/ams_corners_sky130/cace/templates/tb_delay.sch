v {xschem version=3.4.8RC file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {CACE template: propagation delay (tpd_hl, tpd_lh at VDD/2) of the inverter driving CACE\{cload\}} -260 -160 0 0 0.3 0.3 {}
N -240 -60 -240 -30 {lab=VDD}
N -240 30 -240 60 {lab=GND}
N -120 -60 -120 -30 {lab=IN}
N -120 30 -120 60 {lab=GND}
N 260 0 300 0 {lab=IN}
N 380 0 440 0 {lab=OUT}
N 440 0 480 0 {lab=OUT}
N 440 60 440 80 {lab=GND}
N 340 -60 340 -40 {lab=VDD}
N 340 40 340 80 {lab=GND}
C {devices/vsource.sym} -240 0 0 0 {name=Vdd value=CACE\{vdd\} savecurrent=false}
C {devices/lab_pin.sym} -240 -60 0 0 {name=p1 sig_type=std_logic lab=VDD}
C {devices/gnd.sym} -240 60 0 0 {name=l1 lab=GND}
C {devices/vsource.sym} -120 0 0 0 {name=Vin value="pulse(0 CACE\{vdd\} 200p CACE\{tslew\} CACE\{tslew\} 1.8n 4n)" savecurrent=false}
C {devices/lab_pin.sym} -120 -60 0 0 {name=p2 sig_type=std_logic lab=IN}
C {devices/gnd.sym} -120 60 0 0 {name=l2 lab=GND}
C {inverter.sym} 340 0 0 0 {name=x1}
C {devices/lab_pin.sym} 260 0 0 0 {name=p3 sig_type=std_logic lab=IN}
C {devices/lab_pin.sym} 480 0 0 1 {name=p4 sig_type=std_logic lab=OUT}
C {devices/lab_pin.sym} 340 -60 0 0 {name=p5 sig_type=std_logic lab=VDD}
C {devices/gnd.sym} 340 80 0 0 {name=l3 lab=GND}
C {devices/capa.sym} 440 30 0 0 {name=CL m=1 value=CACE\{cload\}}
C {devices/gnd.sym} 440 80 0 0 {name=l4 lab=GND}
C {devices/code_shown.sym} -260 140 0 0 {name=SETUP
simulator=ngspice
only_toplevel=false
value="
* PDK models at the process corner, the circuit's netlist, the temperature
.lib CACE\{PDK_ROOT\}/CACE\{PDK\}/libs.tech/combined/sky130.lib.spice CACE\{corner\}
.include CACE\{DUT_path\}
.temp CACE\{temperature\}

.control
set num_threads=1
tran 1p 4n
meas tran tpd_hl trig v(in) val=CACE[CACE\{vdd\}/2] rise=1 targ v(out) val=CACE[CACE\{vdd\}/2] fall=1
meas tran tpd_lh trig v(in) val=CACE[CACE\{vdd\}/2] fall=1 targ v(out) val=CACE[CACE\{vdd\}/2] rise=1
echo $&tpd_hl $&tpd_lh > CACE\{simpath\}/CACE\{filename\}_CACE\{N\}.data
.endc
"}
