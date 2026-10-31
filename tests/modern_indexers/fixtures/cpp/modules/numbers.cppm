export module numbers;
export template<class T> concept Addable = requires(T a, T b) { a + b; };
export int answer() { return 42; }
