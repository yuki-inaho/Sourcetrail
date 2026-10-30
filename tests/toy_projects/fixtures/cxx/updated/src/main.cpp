#include "api.h"
namespace toy {
int entry() { return replacement(40) + int(replacement(1.5)); }
}
int main() { return toy::entry(); }
