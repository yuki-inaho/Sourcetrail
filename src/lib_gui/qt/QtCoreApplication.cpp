#include "QtCoreApplication.h"

#include <iostream>
#include <QMetaObject>

QtCoreApplication::QtCoreApplication(int argc, char** argv): QCoreApplication(argc, argv) {}

void QtCoreApplication::handleMessage(MessageQuitApplication* message)
{
	std::cout << "Quitting" << std::endl;
	// Message listeners may run on the message-queue thread. exit(int) must run
	// on the QCoreApplication thread; copy the value before the message expires.
	const int exitCode = message->exitCode;
	QMetaObject::invokeMethod(
		this, [exitCode]() { QCoreApplication::exit(exitCode); }, Qt::QueuedConnection);
}

void QtCoreApplication::handleMessage(MessageIndexingStatus* message)
{
	if (message->showProgress)
	{
		std::cout << message->progressPercent << "% " << '\r' << std::flush;
	}
}

void QtCoreApplication::handleMessage(MessageStatus* message)
{
	if (message->isError)
	{
		std::wcout << L"ERROR: ";
	}

	for (const std::wstring& status: message->stati())
	{
		std::wcout << status << std::endl;
	}
}
