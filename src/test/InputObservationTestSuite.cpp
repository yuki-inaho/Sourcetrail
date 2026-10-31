#include "catch.hpp"

#include <fstream>
#include <QTemporaryDir>

#include "FilePath.h"
#include "LocationType.h"
#include "NodeKind.h"
#include "SqliteIndexStorage.h"
#include "TextAccess.h"
#include "SourceChange.h"

namespace
{
class ObservationStorage: public SqliteIndexStorage
{
public:
	explicit ObservationStorage(const FilePath& path): SqliteIndexStorage(path) { setup(); }

	void execute(const std::string& sql) { m_database.execDML(sql.c_str()); }

	Id file(const FilePath& path, const std::string& text)
	{
		std::ofstream output(path.str(), std::ios::binary);
		output.write(text.data(), static_cast<std::streamsize>(text.size()));
		output.close();
		const Id id = addNode(StorageNodeData(nodeKindToInt(NODE_FILE), path.wstr()));
		REQUIRE(addFile(StorageFile(id, path.wstr(), L"python", "", true, true)));
		return id;
	}
};
}

TEST_CASE("checked source reads preserve empty content and the final newline", "[contract][input]")
{
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath path(directory.path().toStdWString() + L"/source.txt");
	REQUIRE_FALSE(TextAccess::tryCreateFromFile(path));
	REQUIRE_FALSE(TextAccess::tryCreateFromFile(FilePath(directory.path().toStdWString())));
	for (const auto& sample: std::vector<std::pair<std::string, std::string>> {
		{"", ""}, {"abc", "abc"}, {"abc\n", "abc\n"},
		{"a\r\nb\r", "a\nb\n"}, {"\xef\xbb\xbf" "変数", "\xef\xbb\xbf" "変数"}})
	{
		std::ofstream output(path.str(), std::ios::binary);
		output << sample.first;
		output.close();
		const auto content = TextAccess::tryCreateFromFile(path);
		REQUIRE(content);
		REQUIRE(content->getText() == sample.second);
	}
}

TEST_CASE("stored content distinguishes empty missing null and SQL failure", "[contract][input]")
{
	using sourcetrail::core::SourceContentStatus;
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath root(directory.path().toStdWString());
	ObservationStorage storage(root.getConcatenated(L"observations.sqlite"));
	const FilePath file = root.getConcatenated(L"source's file.py");
	const Id id = storage.file(file, "");
	REQUIRE(storage.tryGetStoredFileContentByPath(file.wstr()).status == SourceContentStatus::Available);
	REQUIRE(storage.tryGetStoredFileContentByPath(file.wstr()).text.empty());
	storage.execute("UPDATE filecontent SET content=NULL WHERE id=" + std::to_string(id));
	REQUIRE(storage.tryGetStoredFileContentByPath(file.wstr()).status == SourceContentStatus::Null);
	storage.execute("DELETE FROM filecontent WHERE id=" + std::to_string(id));
	REQUIRE(storage.tryGetStoredFileContentByPath(file.wstr()).status == SourceContentStatus::Missing);
	storage.execute("DROP TABLE filecontent");
	REQUIRE(storage.tryGetStoredFileContentByPath(file.wstr()).status == SourceContentStatus::ReadError);
}

TEST_CASE("Python source normalization preserves location identity and ownership", "[contract][location]")
{
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath root(directory.path().toStdWString());
	const FilePath file = root.getConcatenated(L"source.py");
	ObservationStorage storage(root.getConcatenated(L"positions.sqlite"));
	const Id fileId = storage.file(file, "変数 = 1\n");
	const Id node = storage.addNode(StorageNodeData(nodeKindToInt(NODE_GLOBAL_VARIABLE), L"変数"));
	const Id token = storage.addSourceLocation(StorageSourceLocationData(fileId, 1, 1, 1, 2, 0));
	const Id scope = storage.addSourceLocation(StorageSourceLocationData(fileId, 1, 1, 2, 0, 1));
	REQUIRE(storage.addOccurrence(StorageOccurrence(node, token)));
	std::string error;
	REQUIRE(storage.normalizePythonSourceLocations({file, file}, error));
	const auto location = storage.getFirstById<StorageSourceLocation>(token);
	REQUIRE(location.id == token);
	REQUIRE(location.fileNodeId == fileId);
	REQUIRE(location.type == 0);
	REQUIRE(location.startCol == 1);
	REQUIRE(location.endCol == 6);
	const auto end = storage.getFirstById<StorageSourceLocation>(scope);
	REQUIRE(end.endLine == 1);
	REQUIRE(end.endCol == 10);
	const auto occurrences = storage.getOccurrencesForLocationId(token);
	REQUIRE(occurrences.size() == 1);
	REQUIRE(occurrences[0].elementId == node);
}

TEST_CASE("invalid Python output rolls back all source position updates", "[contract][location]")
{
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath root(directory.path().toStdWString());
	const FilePath first = root.getConcatenated(L"a.py");
	const FilePath second = root.getConcatenated(L"z.py");
	ObservationStorage storage(root.getConcatenated(L"rollback.sqlite"));
	const Id firstId = storage.file(first, "変数 = 1\n");
	const Id secondId = storage.file(second, "x = 2\n");
	const Id token = storage.addSourceLocation(StorageSourceLocationData(firstId, 1, 1, 1, 2, 0));
	storage.addSourceLocation(StorageSourceLocationData(secondId, 3, 1, 3, 2, 0));
	std::string error;
	REQUIRE_FALSE(storage.normalizePythonSourceLocations({first, second}, error));
	REQUIRE_FALSE(error.empty());
	REQUIRE(storage.getFirstById<StorageSourceLocation>(token).endCol == 2);
}

TEST_CASE("legacy Python empty output materializes an explicit empty observation", "[contract][input]")
{
	using sourcetrail::core::SourceContentStatus;
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath root(directory.path().toStdWString());
	const FilePath file = root.getConcatenated(L"empty.py");
	ObservationStorage storage(root.getConcatenated(L"empty.sqlite"));
	const Id fileId = storage.file(file, "");
	storage.execute("DELETE FROM filecontent");
	std::string error;
	SECTION("the fixed writer may omit the empty content row")
	{
		REQUIRE(storage.normalizePythonSourceLocations({file}, error));
		const auto content = storage.tryGetStoredFileContentByPath(file.wstr());
		REQUIRE(content.status == SourceContentStatus::Available);
		REQUIRE(content.text.empty());
	}
	SECTION("missing content with source locations remains invalid")
	{
		storage.addSourceLocation(StorageSourceLocationData(fileId, 1, 1, 1, 0, 6));
		REQUIRE_FALSE(storage.normalizePythonSourceLocations({file}, error));
		REQUIRE(storage.tryGetStoredFileContentByPath(file.wstr()).status == SourceContentStatus::Missing);
	}
}

TEST_CASE("Python output cannot hide NUL truncated source or changed contents", "[contract][location]")
{
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath root(directory.path().toStdWString());
	const FilePath file = root.getConcatenated(L"source.py");
	ObservationStorage storage(root.getConcatenated(L"invalid.sqlite"));
	storage.file(file, std::string("x = 1\0\nx = 2\n", 13));
	std::string error;
	REQUIRE_FALSE(storage.normalizePythonSourceLocations({file}, error));
	REQUIRE_FALSE(error.empty());
}
