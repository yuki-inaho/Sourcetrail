use shapes::{Measure, Square};

fn run() -> i32 {
    let square = Square::new(3);
    square.measure() + shapes::twice(2)
}

fn main() {
    let _result = run();
}

