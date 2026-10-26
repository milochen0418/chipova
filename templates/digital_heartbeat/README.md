# Heartbeat

A small counter that pulses its output once every 2^N clocks: the "hello world" of chip design.

1. **Lint** checks the RTL with Verilator.
2. **Simulate** runs `tb/tb_heartbeat.v` with Icarus Verilog; the testbench prints `PASS` when the
   pulses come exactly every 2^N clocks, and the waveform opens in the Waveform tab.
3. **Synthesize** maps it to generic gates with Yosys.
4. **Build ASIC** takes it through SiliconCompiler (Yosys, OpenROAD, KLayout) to a GDSII layout
   on the open SkyWater 130 nm PDK.
