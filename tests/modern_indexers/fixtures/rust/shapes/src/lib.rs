pub mod operations;
pub use operations::double as twice;

pub trait Measure {
    fn measure(&self) -> i32;
}

pub struct Square {
    pub side: i32,
}

impl Square {
    pub fn new(side: i32) -> Self {
        Self { side }
    }
}

impl Measure for Square {
    fn measure(&self) -> i32 {
        operations::double(self.side)
    }
}

macro_rules! identity {
    ($expression:expr) => {
        $expression
    };
}

pub fn 計算(value: i32) -> i32 {
    identity!(operations::double(value))
}

#[cfg(feature = "extra")]
pub fn optional() -> i32 {
    7
}

#[cfg(custom_mode)]
pub fn configured() -> i32 {
    11
}

pub fn machine_width() -> usize {
    std::mem::size_of::<i32>()
}

#[cfg(test)]
pub fn test_only() -> i32 {
    17
}

