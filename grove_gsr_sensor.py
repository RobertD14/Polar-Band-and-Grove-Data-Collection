import sys
import time

from grove.adc import ADC


class GroveGSRSensor:
    def __init__(self, channel):
        self.channel = channel
        self.adc = ADC()

    @property
    def GSR(self):
        value = self.adc.read(self.channel)
        return value


Grove = GroveGSRSensor


def main():
    if len(sys.argv) < 2:
        print("Usage: {} adc_channel".format(sys.argv[0]))
        sys.exit(1)

    sensor = GroveGSRSensor(int(sys.argv[1]))

    print("Detecting...")
    while True:
        print("GSR value: {0}".format(sensor.GSR))
        time.sleep(0.3)


if __name__ == "__main__":
    main()
