#include "catch.hpp"

#include "language_packages.h"

#if BUILD_CXX_LANGUAGE_PACKAGE

#	include <algorithm>
#	include <map>
#	include <memory>
#	include <set>
#	include <string>
#	include <vector>

#	include <QCoreApplication>
#	include <QDateTime>
#	include <QDir>
#	include <QFile>
#	include <QFileInfo>
#	include <QJsonArray>
#	include <QJsonDocument>
#	include <QJsonObject>
#	include <QProcess>
#	include <QProcessEnvironment>
#	include <QTemporaryDir>

#	include "CxxTestGraph.h"
#	include "SqliteIndexStorage.h"

#	ifndef SOURCETRAIL_TEST_APP_PATH
#		define SOURCETRAIL_TEST_APP_PATH ""
#	endif

namespace
{
struct IndexSnapshot
{
	std::vector<StorageNode> nodes;
	std::vector<StorageEdge> edges;
	std::vector<StorageFile> files;
	std::vector<StorageError> errors;
	int sourceLocationCount;
	std::string processOutput;
};

// Each case launches the real application and reads its on-disk database only after it exits.
// No parser, subprocess, or database implementation is substituted by the test.
class CommandlineProject
{
public:
	CommandlineProject()
		: m_directory(QDir::tempPath() + QStringLiteral("/sourcetrail cxx e2e-XXXXXX"))
	{
		if (!QCoreApplication::instance())
		{
			m_application = std::make_unique<QCoreApplication>(m_argc, m_argv);
		}
		REQUIRE(m_directory.isValid());
		m_binary = qEnvironmentVariable("SOURCETRAIL_BINARY");
		if (m_binary.isEmpty())
		{
			m_binary = QString::fromUtf8(SOURCETRAIL_TEST_APP_PATH);
		}
		INFO("Build Sourcetrail or set SOURCETRAIL_BINARY to its executable.");
		REQUIRE_FALSE(m_binary.isEmpty());
		REQUIRE(QFileInfo(m_binary).isExecutable());
		m_binary = QFileInfo(m_binary).absoluteFilePath();

		writeFile(
			QStringLiteral("home/.config/sourcetrail/ApplicationSettings.xml"),
			"<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
			"<config><version>8</version><indexing>"
			"<indexer_thread_count>1</indexer_thread_count>"
			"<multi_process_indexing>0</multi_process_indexing>"
			"<cxx><has_prefilled_header_search_paths>1</has_prefilled_header_search_paths>"
			"<has_prefilled_framework_search_paths>1</has_prefilled_framework_search_paths>"
			"</cxx></indexing></config>\n");
		writeFile(
			QStringLiteral("fixture.srctrlprj"),
			"<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
			"<config><version>8</version><source_groups><source_group_e2e>"
			"<name>C++ command line E2E</name><status>enabled</status>"
			"<type>C/C++ from Compilation Database</type>"
			"<build_file_path><compilation_db_path>compile_commands.json</compilation_db_path>"
			"</build_file_path><indexed_header_paths>"
			"<indexed_header_path>include</indexed_header_path>"
			"</indexed_header_paths></source_group_e2e></source_groups></config>\n");
		writeSources("helper");

		QJsonArray commands;
		for (const QString& source:
			 {QStringLiteral("src/main.cpp"), QStringLiteral("src/helper.cpp")})
		{
			QJsonObject command;
			command.insert(QStringLiteral("directory"), m_directory.path());
			command.insert(QStringLiteral("file"), path(source));
			command.insert(
				QStringLiteral("arguments"),
				QJsonArray {
					QStringLiteral("clang++"),
					QStringLiteral("-std=c++17"),
					QStringLiteral("-I"),
					path(QStringLiteral("include")),
					QStringLiteral("-c"),
					path(source)});
			commands.append(command);
		}
		writeFile(QStringLiteral("compile_commands.json"), QJsonDocument(commands).toJson());
	}

	QString path(const QString& relativePath) const
	{
		return QDir(m_directory.path()).filePath(relativePath);
	}

	void writeFile(const QString& relativePath, const QByteArray& contents, bool advanceTime = false)
	{
		const QString filePath = path(relativePath);
		const QDateTime previousTime = QFileInfo(filePath).lastModified();
		REQUIRE(QDir().mkpath(QFileInfo(filePath).absolutePath()));
		QFile file(filePath);
		INFO("Writing fixture: " << filePath.toStdString());
		REQUIRE(file.open(QIODevice::WriteOnly | QIODevice::Truncate));
		REQUIRE(file.write(contents) == contents.size());
		REQUIRE(file.flush());
		if (advanceTime)
		{
			// Refresh detection stores timestamps at second resolution; avoid sleeps and races.
			REQUIRE(previousTime.isValid());
			REQUIRE(file.setFileTime(previousTime.addSecs(2), QFileDevice::FileModificationTime));
		}
	}

	void setModificationTime(const QString& relativePath, const QDateTime& modified)
	{
		QFile file(path(relativePath));
		REQUIRE(file.open(QIODevice::ReadWrite));
		REQUIRE(file.setFileTime(modified, QFileDevice::FileModificationTime));
	}

	void writeSources(const QByteArray& functionName, bool advanceTime = false)
	{
		writeFile(
			QStringLiteral("include/api.h"),
			"#pragma once\nnamespace sample { int " + functionName + "(int value); }\n",
			advanceTime);
		writeFile(
			QStringLiteral("src/helper.cpp"),
			"#include \"api.h\"\nnamespace sample { int " + functionName +
				"(int value) { return value + 2; } }\n",
			advanceTime);
		writeFile(QStringLiteral("src/main.cpp"), mainSource(functionName), advanceTime);
	}

	static QByteArray mainSource(const QByteArray& functionName)
	{
		return "#include \"api.h\"\nint main() { return sample::" + functionName + "(40); }\n";
	}

	void index(const QStringList& options = {})
	{
		QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
		// Linux Sourcetrail explicitly uses HOME/.config/sourcetrail, not XDG_CONFIG_HOME.
		environment.insert(QStringLiteral("HOME"), path(QStringLiteral("home")));
		environment.insert(QStringLiteral("XDG_CONFIG_HOME"), path(QStringLiteral("home/.config")));
		environment.insert(
			QStringLiteral("XDG_DATA_HOME"), path(QStringLiteral("home/.local/share")));
		environment.insert(QStringLiteral("XDG_CACHE_HOME"), path(QStringLiteral("home/.cache")));
		environment.insert(QStringLiteral("SOURCETRAIL_VIA_SCRIPT"), QStringLiteral("1"));
		environment.insert(QStringLiteral("QT_QPA_PLATFORM"), QStringLiteral("offscreen"));

		QProcess process;
		process.setProcessEnvironment(environment);
		process.setProcessChannelMode(QProcess::MergedChannels);
		process.setWorkingDirectory(m_directory.path());
		QStringList arguments {QStringLiteral("index")};
		arguments.append(options);
		arguments.append(path(QStringLiteral("fixture.srctrlprj")));
		process.start(m_binary, arguments);
		const bool started = process.waitForStarted(10000);
		INFO("Starting Sourcetrail: " << process.errorString().toStdString());
		REQUIRE(started);
		const bool finished = process.waitForFinished(120000);
		if (!finished)
		{
			// The isolated settings keep indexing in this process, so no worker is orphaned.
			process.kill();
			process.waitForFinished(5000);
		}
		m_output = process.readAll().toStdString();
		INFO(m_output);
		REQUIRE(finished);
		REQUIRE(process.exitStatus() == QProcess::NormalExit);
		REQUIRE(process.exitCode() == 0);
	}

	IndexSnapshot readIndex() const
	{
		INFO(m_output);
		const QString databasePath = path(QStringLiteral("fixture.srctrldb"));
		REQUIRE(QFileInfo(databasePath).isFile());
		REQUIRE(QFileInfo(databasePath).size() > 0);
		SqliteIndexStorage storage(FilePath(databasePath.toStdWString()));
		// Do not call setup(): an absent or incomplete schema must never be created by a test.
		REQUIRE(storage.getVersion() == SqliteIndexStorage::getStorageVersion());
		return {
			storage.getAll<StorageNode>(),
			storage.getAll<StorageEdge>(),
			storage.getAll<StorageFile>(),
			storage.getAll<StorageError>(),
			storage.getSourceLocationCount(),
			m_output};
	}

private:
	int m_argc = 1;
	char m_program[25] = "Sourcetrail C++ E2E test";
	char* m_argv[2] = {m_program, nullptr};
	std::unique_ptr<QCoreApplication> m_application;
	QTemporaryDir m_directory;
	QString m_binary;
	std::string m_output;
};

void requireHealthyIndex(const IndexSnapshot& index, const std::wstring& functionName)
{
	INFO(index.processOutput);
	REQUIRE(index.errors.empty());
	REQUIRE(index.files.size() == 3);
	std::set<std::wstring> filenames;
	std::map<std::wstring, Id> fileIds;
	for (const StorageFile& file: index.files)
	{
		INFO("Indexed file: " << utility::encodeToUtf8(file.filePath));
		REQUIRE(file.indexed);
		REQUIRE(file.complete);
		filenames.insert(FilePath(file.filePath).fileName());
		fileIds.emplace(FilePath(file.filePath).fileName(), file.id);
	}
	const std::set<std::wstring> expectedFilenames {L"api.h", L"helper.cpp", L"main.cpp"};
	REQUIRE(filenames == expectedFilenames);
	REQUIRE(index.sourceLocationCount > 0);
	const Id main = cxx_test::requireUniqueNode(index.nodes, L"int main()");
	const Id helper = cxx_test::requireUniqueNode(
		index.nodes, L"int sample::" + functionName + L"(int)");
	REQUIRE(cxx_test::hasEdge(index.edges, Edge::EDGE_CALL, main, helper));
	REQUIRE(cxx_test::hasEdge(
		index.edges, Edge::EDGE_INCLUDE, fileIds.at(L"main.cpp"), fileIds.at(L"api.h")));
	REQUIRE(cxx_test::hasEdge(
		index.edges, Edge::EDGE_INCLUDE, fileIds.at(L"helper.cpp"), fileIds.at(L"api.h")));
}

std::set<std::wstring> semanticGraph(const IndexSnapshot& index)
{
	std::map<Id, std::wstring> names;
	std::set<std::wstring> graph;
	for (const StorageNode& node: index.nodes)
	{
		const std::wstring name =
			NameHierarchy::deserialize(node.serializedName).getQualifiedNameWithSignature();
		names.emplace(node.id, name);
		graph.insert(L"node " + std::to_wstring(node.type) + L" " + name);
	}
	for (const StorageEdge& edge: index.edges)
	{
		REQUIRE(names.count(edge.sourceNodeId) == 1);
		REQUIRE(names.count(edge.targetNodeId) == 1);
		graph.insert(
			L"edge " + std::to_wstring(edge.type) + L" " + names.at(edge.sourceNodeId) + L" -> " +
			names.at(edge.targetNodeId));
	}
	return graph;
}
}	 // namespace

TEST_CASE(
	"cxx e2e indexes a compilation database and leaves an unchanged graph stable", "[cxx][e2e]")
{
	CommandlineProject project;
	project.index({QStringLiteral("--full")});
	const IndexSnapshot original = project.readIndex();
	requireHealthyIndex(original, L"helper");

	project.index();
	const IndexSnapshot unchanged = project.readIndex();
	requireHealthyIndex(unchanged, L"helper");
	REQUIRE(semanticGraph(unchanged) == semanticGraph(original));
	REQUIRE(unchanged.nodes.size() == original.nodes.size());
	REQUIRE(unchanged.edges.size() == original.edges.size());
	REQUIRE(unchanged.sourceLocationCount == original.sourceLocationCount);
}

TEST_CASE("cxx e2e incremental indexing removes renamed symbols and stale calls", "[cxx][e2e]")
{
	CommandlineProject project;
	project.index({QStringLiteral("--full")});
	requireHealthyIndex(project.readIndex(), L"helper");

	project.writeSources("replacement", true);
	project.index();
	const IndexSnapshot updated = project.readIndex();
	requireHealthyIndex(updated, L"replacement");
	REQUIRE(cxx_test::findNodes(updated.nodes, L"int sample::helper(int)").empty());
	semanticGraph(updated);	   // Also reject any dangling edge endpoints after cleanup.
}

TEST_CASE("cxx e2e records compiler errors and repairs incomplete files", "[cxx][e2e]")
{
	CommandlineProject project;
	const QString mainPath = QStringLiteral("src/main.cpp");
	project.writeFile(mainPath, "#include \"api.h\"\nint main() { return missing_symbol; }\n");
	const QDateTime originalTime = QFileInfo(project.path(mainPath)).lastModified();
	project.index({QStringLiteral("--full")});
	const IndexSnapshot broken = project.readIndex();
	REQUIRE_FALSE(broken.errors.empty());
	REQUIRE(std::any_of(broken.errors.begin(), broken.errors.end(), [](const StorageError& error) {
		return error.indexed && error.message.find(L"missing_symbol") != std::wstring::npos;
	}));
	REQUIRE(std::any_of(broken.files.begin(), broken.files.end(), [](const StorageFile& file) {
		return FilePath(file.filePath).fileName() == L"main.cpp" && !file.complete;
	}));

	project.writeFile(mainPath, CommandlineProject::mainSource("helper"));
	// Preserve mtime so this specifically exercises --incomplete, not changed-file discovery.
	project.setModificationTime(mainPath, originalTime);
	project.index({QStringLiteral("--incomplete")});
	requireHealthyIndex(project.readIndex(), L"helper");
}

#endif	  // BUILD_CXX_LANGUAGE_PACKAGE
