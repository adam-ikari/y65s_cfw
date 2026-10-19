#include "kbdef.h"
#include "user_init.h"
#include "gpio.h"

void user_init(void)
{
    // Rows are inputs with pull-ups; the scanner only ever drives columns.
    GPIO_INPUT(5, KB_R3_P5_3 | KB_R4_P5_4);
    GPIO_INPUT(7, KB_R0_P7_1 | KB_R1_P7_2 | KB_R2_P7_3);
    GPIO_PULLUP_ON(5, KB_R3_P5_3 | KB_R4_P5_4);
    GPIO_PULLUP_ON(7, KB_R0_P7_1 | KB_R1_P7_2 | KB_R2_P7_3);

    // Columns idle high.  scan_pre/scan_post flip the direction each scan.
    GPIO_DIR_WRITE(6, (uint8_t)(KB_C0_P6_0 | KB_C1_P6_1 | KB_C2_P6_2 | KB_C3_P6_3 |
                                KB_C4_P6_4 | KB_C5_P6_5 | KB_C6_P6_6 | KB_C7_P6_7));
    GPIO_HIGH(6, 0xFF);

    GPIO_DIR_WRITE(5, (uint8_t)(KB_C8_P5_0 | KB_C9_P5_1 | KB_C10_P5_2 | KB_C11_P5_7));
    GPIO_HIGH(5, (uint8_t)(KB_C8_P5_0 | KB_C9_P5_1 | KB_C10_P5_2 | KB_C11_P5_7));

    GPIO_DIR_WRITE(4, (uint8_t)(KB_C12_P4_0 | KB_C14_P4_5));
    GPIO_HIGH(4, (uint8_t)(KB_C12_P4_0 | KB_C14_P4_5));

    GPIO_DIR_WRITE(7, (uint8_t)(KB_C13_P7_7));
    GPIO_HIGH(7, (uint8_t)(KB_C13_P7_7));
}
