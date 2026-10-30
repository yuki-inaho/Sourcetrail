from library import Parent, helper


class Child(Parent):
    def run(self):
        return Parent.run(self)


def entry():
    return helper(41)
