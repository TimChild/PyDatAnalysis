from src.Sandbox import *
import src.DatCode.Transition as T
import src.DatCode.Entropy as E


class testclass(object):

    ca = 1
    bs = {}

    @classmethod
    def get_value(cls, b):
        if b in cls.bs:
            return cls.bs[b]
        else:
            cls.bs[b] = cls.ca
            cls.ca += 1
            return cls.bs[b]


class testclass2(object):
    def __init__(self):
        self.a = 10
        self.test = 15

    @property
    def test(self):
        if self._test is not None:
            return self._test*2
        else:
            return 10

    @test.setter
    def test(self, value):
        self._test = value


class Outer_printer(object):
    def __init__(self, b):
        self.b = 10

    def print_a(self):
        print(self.a)


class Outer(Outer_printer):
    def __init__(self, b):
        super().__init__(b)
        self.a = 1
        self.print_a()

    class inner(object):
        @staticmethod
        def print(outer, msg):
            print(outer.a, msg)


    @staticmethod
    def print_hi():
        print('hello')

if __name__ == '__main__':
    x = np.linspace(0, 10, 10000)
    y = np.sin(x)

    x1, y1 = CU.bin_data([x, y], 1000)
    fig, ax = plt.subplots(1)
    ax.plot(x,y)
    ax.plot(x1, y1)
