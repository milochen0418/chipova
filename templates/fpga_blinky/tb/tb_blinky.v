`timescale 1ns / 1ps
// With a 4-bit counter the green LED must change every 8 clocks; the red one follows the button.
module tb_blinky;
    reg  clk = 1'b0;
    reg  btn_n = 1'b1;
    wire ledr_n, ledg_n;

    blinky #(.WIDTH(4)) dut (.CLK(clk), .BTN_N(btn_n), .LEDR_N(ledr_n), .LEDG_N(ledg_n));

    always #41.667 clk = ~clk;  // 12 MHz

    integer changes = 0;
    integer errors = 0;
    reg last_g;

    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_blinky);
        @(posedge clk);
        last_g = ledg_n;
        repeat (32) begin
            @(posedge clk);
            #1;
            if (ledg_n !== last_g) begin
                changes = changes + 1;
                last_g = ledg_n;
            end
        end
        btn_n = 1'b0;
        #5;
        if (ledr_n !== 1'b0) begin
            $display("ERROR red LED is off while the button is pressed");
            errors = errors + 1;
        end
        if (changes != 4) begin
            $display("ERROR green LED changed %0d times in 32 clocks, expected 4", changes);
            errors = errors + 1;
        end
        if (errors == 0) $display("PASS blinky");
        else $display("FAIL blinky: %0d errors", errors);
        $finish;
    end
endmodule
