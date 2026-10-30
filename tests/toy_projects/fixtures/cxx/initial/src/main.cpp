#include "api.h"
namespace toy {
int entry() { return answer(40) + int(answer(1.5)); }
}
int main() { return toy::entry(); }
