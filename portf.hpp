#ifndef AVRLIB_PORTF_HPP
#define AVRLIB_PORTF_HPP

#include <avr/io.h>

namespace avrlib {

struct portf
{
	static uint8_t port() { return PORTF; }
	static void port(uint8_t v) { PORTF = v; }

	static uint8_t pin() { return PINF; }
	static void pin(uint8_t v) { PINF = v; }

	static uint8_t dir() { return DDRF; }
	static void dir(uint8_t v) { DDRF = v; }

	static uint8_t* get_address() { return &PORTF; }

	static volatile uint8_t* get_pin_address() { return &PINF; }
};

}

#endif
