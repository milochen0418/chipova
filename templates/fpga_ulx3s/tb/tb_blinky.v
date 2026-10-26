`timescale 1ns / 1ps
// With a 10-bit counter the LEDs show a new value every 4 clocks; FIRE1 lights them all.
module tb_blinky;
    reg        clk = 1'b0;
    reg  [1:0] btn = 2'b01;  // the power button not pressed (high), FIRE1 not pressed (low)
    wire [7:0] led;

    blinky #(.WIDTH(10)) dut (.clk_25mhz(clk), .btn(btn), .led(led));

    always #20 clk = ~clk;  // 25 MHz

    integer k;
    integer errors = 0;

    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_blinky);
        for (k = 1; k <= 64; k = k + 1) begin
            @(posedge clk);
            #1;
            if (led !== ((k >> 2) & 8'hFF)) begin
                $display("ERROR after %0d clocks the LEDs show %b, expected %b", k, led, (k >> 2) & 8'hFF);
                errors = errors + 1;
            end
        end
        btn[1] = 1'b1;
        #1;
        if (led !== 8'hFF) begin
            $display("ERROR FIRE1 is held but the LEDs show %b", led);
            errors = errors + 1;
        end
        if (errors == 0) $display("PASS blinky");
        else $display("FAIL blinky: %0d errors", errors);
        $finish;
    end
endmodule
