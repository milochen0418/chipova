// Blinky for the iCEBreaker (iCE40 UP5K, 12 MHz clock):
// the green LED blinks about once a second, the red one lights while the button is held.
module blinky #(
    parameter WIDTH = 24
) (
    input  wire CLK,
    input  wire BTN_N,   // the user button, low when pressed
    output wire LEDR_N,  // LEDs light when driven low
    output wire LEDG_N
);

    reg [WIDTH-1:0] count = {WIDTH{1'b0}};

    always @(posedge CLK)
        count <= count + 1'b1;

    assign LEDG_N = ~count[WIDTH-1];
    assign LEDR_N = BTN_N;

endmodule
