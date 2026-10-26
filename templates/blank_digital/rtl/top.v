module top (
    input  wire clk,
    input  wire nreset,
    output wire done
);

    assign done = nreset;

endmodule
