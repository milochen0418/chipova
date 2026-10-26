// Blinky for the ULX3S (Lattice ECP5, 25 MHz clock): the eight LEDs show a counter's top bits
// (a new value about six times a second); FIRE1, or the power button, lights them all.
module blinky #(
    parameter WIDTH = 28
) (
    input  wire       clk_25mhz,
    input  wire [1:0] btn,  // btn[0]: the power button, low when pressed; btn[1]: FIRE1, high
    output wire [7:0] led   // high = on
);

    reg [WIDTH-1:0] count = {WIDTH{1'b0}};

    always @(posedge clk_25mhz)
        count <= count + 1'b1;

    assign led = (btn[1] || !btn[0]) ? 8'hFF : count[WIDTH-1 -: 8];

endmodule
