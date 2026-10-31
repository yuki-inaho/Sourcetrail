#include "Utf8SourceLocationMap.h"

#include <iostream>
#include <stdexcept>

namespace
{
void require(bool valid)
{
	if (!valid) throw std::runtime_error("LOCATION-001 UTF-8 mapping mismatch");
}

void expectRange(const sourcetrail::core::SourceRange& actual,
	std::size_t sl, std::size_t sc, std::size_t el, std::size_t ec)
{
	require(actual.startLine == sl && actual.startColumn == sc &&
		actual.endLine == el && actual.endColumn == ec);
}
}

int main()
{
	using namespace sourcetrail::core;
	try
	{
		const Utf8SourceLocationMap unicode("変数 = '😀'\nx = 変数\n");
		expectRange(unicode.toBytes({1, 1, 1, 2}), 1, 1, 1, 6);
		expectRange(unicode.toBytes({1, 7, 1, 7}), 1, 11, 1, 14);
		expectRange(unicode.toBytes({2, 5, 2, 6}), 2, 5, 2, 10);
		expectRange(unicode.toBytes({1, 1, 3, 0}, true), 1, 1, 2, 10);
		const Utf8SourceLocationMap bom("\xef\xbb\xbf" "変数 = 1");
		expectRange(bom.toBytes({1, 1, 1, 2}), 1, 4, 1, 9);
		expectRange(bom.toBytes({1, 1, 2, 0}, true), 1, 4, 1, 13);
		const Utf8SourceLocationMap empty("");
		expectRange(empty.toBytes({1, 1, 1, 0}, true), 1, 1, 1, 1);
		const Utf8SourceLocationMap ascii("abc");
		expectRange(ascii.toBytes({1, 4, 1, 3}, true), 1, 4, 1, 4);
		std::size_t rejected = 0;
		for (const SourceRange range: {SourceRange {0, 1, 1, 1}, {1, 0, 1, 1},
			{1, 5, 1, 5}, {1, 1, 2, 1}, {1, 2, 1, 0}, {1, 1, 1, 4}, {1, 4, 1, 3}})
		{
			try { ascii.toBytes(range); }
			catch (const std::invalid_argument&) { ++rejected; }
		}
		require(rejected == 7);
		for (const std::string& invalid: {std::string("a\0b", 3), std::string("\r"),
			std::string("\xc0\x80"), std::string("\xed\xa0\x80"),
			std::string("\xf4\x90\x80\x80"), std::string("\xe6\x97"), std::string("\x80")})
		{
			try { Utf8SourceLocationMap map(invalid); }
			catch (const std::invalid_argument&) { ++rejected; }
		}
		require(rejected == 14);
		std::cout << "LOCATION-001: 8 authored ranges and 14 invalid inputs passed\n";
		return 0;
	}
	catch (const std::exception& error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
