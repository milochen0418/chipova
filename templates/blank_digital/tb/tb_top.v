`timescale 1ns / 1ps
module tb_top;
    reg  clk = 1'b0;
    reg  nreset = 1'b0;
    wire done;

    top dut (.clk(clk), .nreset(nreset), .done(done));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_top);
        #20 nreset = 1'b1;
        #20;
        if (done === 1'b1) $display("PASS top");
        else $display("FAIL top: done is %b", done);
        $finish;
    end
endmodule
