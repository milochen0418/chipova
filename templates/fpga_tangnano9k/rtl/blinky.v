// Blinky for the Sipeed Tang Nano 9K (Gowin GW1NR-9, 27 MHz clock): the six LEDs show a
// counter's top bits; S1 lights them all. The LEDs light when driven low.
module blinky #(
    parameter WIDTH = 28
) (
    input  wire       clk,
    input  wire       btn_s1,  // low when pressed
    output wire [5:0] led      // low = on
);

    reg [WIDTH-1:0] count = {WIDTH{1'b0}};

    always @(posedge clk)
        count <= count + 1'b1;

    assign led = btn_s1 ? ~count[WIDTH-1 -: 6] : 6'b000000;

endmodule
