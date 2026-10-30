from library import Parent, replacement


class Child(Parent):
    def run(self):
        return Parent.run(self)


def entry():
    return replacement(41)
