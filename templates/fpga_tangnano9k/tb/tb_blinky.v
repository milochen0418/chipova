`timescale 1ns / 1ps
// With an 8-bit counter the LEDs (low = on) show a new value every 4 clocks; S1 lights them all.
module tb_blinky;
    reg        clk = 1'b0;
    reg        btn_s1 = 1'b1;  // not pressed
    wire [5:0] led;

    blinky #(.WIDTH(8)) dut (.clk(clk), .btn_s1(btn_s1), .led(led));

    always #18.519 clk = ~clk;  // 27 MHz

    integer k;
    integer errors = 0;

    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_blinky);
        for (k = 1; k <= 64; k = k + 1) begin
            @(posedge clk);
            #1;
            if (led !== (~(k >> 2) & 6'h3F)) begin
                $display("ERROR after %0d clocks the LEDs show %b, expected %b", k, led, ~(k >> 2) & 6'h3F);
                errors = errors + 1;
            end
        end
        btn_s1 = 1'b0;
        #1;
        if (led !== 6'b000000) begin
            $display("ERROR S1 is held but the LEDs show %b", led);
            errors = errors + 1;
        end
        if (errors == 0) $display("PASS blinky");
        else $display("FAIL blinky: %0d errors", errors);
        $finish;
    end
endmodule
