namespace modern {
template <class T>
concept Addable = requires(T left, T right) { left + right; };

template <Addable T>
T combine(T left, T right) { return left + right; }

consteval int factor() { return 2; }
constexpr int choose(int value) {
    if consteval { return factor(); }
    else { return value; }
}

struct Point { int x; int y; };
int run() {
    Point point{.x = choose(3), .y = 4};
    auto increment = []<typename T>(T value) { return value + 1; };
    return combine(point.x, point.y) + increment(1);
}
}
