/*
**	Command & Conquer Generals Zero Hour(tm)
**	Copyright 2025 Electronic Arts Inc.
**
**	This program is free software: you can redistribute it and/or modify
**	it under the terms of the GNU General Public License as published by
**	the Free Software Foundation, either version 3 of the License, or
**	(at your option) any later version.
**
**	This program is distributed in the hope that it will be useful,
**	but WITHOUT ANY WARRANTY; without even the implied warranty of
**	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
**	GNU General Public License for more details.
**
**	You should have received a copy of the GNU General Public License
**	along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#include "PreRTS.h"	// This must go first in EVERY cpp file in the GameEngine

#include "Common/WinPredictorExport.h"

#include "Common/Energy.h"
#include "Common/GameCommon.h"
#include "Common/GlobalData.h"
#include "Common/Money.h"
#include "Common/NameKeyGenerator.h"
#include "Common/Player.h"
#include "Common/PlayerList.h"
#include "Common/PlayerTemplate.h"
#include "Common/Recorder.h"
#include "Common/ScoreKeeper.h"
#include "Common/ThingTemplate.h"
#include "Common/MessageStream.h"
#include "Common/Upgrade.h"
#include "GameLogic/GameLogic.h"
#include "GameLogic/Object.h"
#include "GameLogic/TerrainLogic.h"
#include "GameLogic/Module/BehaviorModule.h"
#include "GameLogic/Module/ProductionUpdate.h"
#include "GameLogic/Module/SpecialPowerModule.h"
#include "GameClient/Display.h"
#include "GameClient/DisplayString.h"
#include "GameClient/DisplayStringManager.h"
#include "GameClient/GameWindowManager.h"
#include "GameClient/GlobalLanguage.h"

#include <stdio.h>
#include <string.h>
#include <map>
#include <vector>

namespace
{

const Int SAMPLE_INTERVAL_FRAMES = 30;
const Int GRID_DIM = 8;

Bool s_active = FALSE;
Bool s_matchStarted = FALSE;
UnsignedInt s_lastSeenFrame = 0;
char s_csvPath[1024] = {0};

UnsignedInt s_cmdCount[MAX_PLAYER_COUNT] = {0};

Bool s_extentValid = FALSE;
Real s_extLoX = 0, s_extLoY = 0, s_extSpanX = 1, s_extSpanY = 1;

AsciiString getExportDir()
{
	return TheGlobalData->getPath_UserData();
}

Bool getStateCsvPath(AsciiString &path)
{
	if (TheGlobalData == nullptr)
		return FALSE;
	path = getExportDir();
	if (path.isEmpty())
		return FALSE;
	path.concat("state.csv");
	return TRUE;
}

void sanitizeForCsv(AsciiString &s)
{
	char buf[256];
	const char *src = s.str();
	Int j = 0;
	for (Int i = 0; src[i] != 0 && j < 255; ++i)
	{
		char c = src[i];
		buf[j++] = (c == ',' || c == '\n' || c == '\r') ? ' ' : c;
	}
	buf[j] = 0;
	s = buf;
}

Bool isRealPlayer(Player *player)
{
	if (player == nullptr || player == ThePlayerList->getNeutralPlayer())
		return FALSE;
	if (player->getPlayerTemplate() == nullptr)
		return FALSE;
	const PlayerTemplate *civTemplate =
		ThePlayerTemplateStore->findPlayerTemplate(NAMEKEY("FactionCivilian"));
	if (player->getPlayerTemplate() == civTemplate)
		return FALSE;
	if (player->isPlayerObserver())
		return FALSE;
	return TRUE;
}

// Mallow: never collect state or draw predictions during online play.
Bool isOnlineGame()
{
	return TheGameLogic != nullptr && TheGameLogic->isInInternetGame();
}

void startMatchFile()
{
	AsciiString path;
	if (!getStateCsvPath(path))
	{
		s_active = FALSE;
		return;
	}
	strlcpy(s_csvPath, path.str(), ARRAY_SIZE(s_csvPath));

	AsciiString predPath = getExportDir();
	predPath.concat("prediction.txt");
	remove(predPath.str());

	FILE *f = fopen(s_csvPath, "w");
	if (f == nullptr)
	{
		s_active = FALSE;
		return;
	}

	AsciiString mapName = TheGlobalData->m_mapName;
	sanitizeForCsv(mapName);
	AsciiString replayName;
	if (TheRecorder != nullptr && TheRecorder->getMode() != RECORDERMODETYPE_RECORD)
		replayName = TheRecorder->getCurrentReplayFilename();
	sanitizeForCsv(replayName);

	fprintf(f, "META,%s,%s,%u\n", mapName.str(), replayName.str(),
		(unsigned int)time(nullptr));
	fprintf(f, "#STATE,frame,playerIndex,name,side,money,moneyEarned,moneySpent,"
		"unitsBuilt,unitsLost,unitsDestroyed,bldgsBuilt,bldgsLost,bldgsDestroyed,"
		"techCaptured,factionCaptured,energyProd,energyCons,"
		"unitCount,unitValue,structCount,structValue,"
		"heroicCount,swCount,swMaxReady,queueCount,queueValue,cmdCount,"
		"comp,ugrid,sgrid\n");
	fclose(f);
	s_active = TRUE;

	for (Int i = 0; i < MAX_PLAYER_COUNT; ++i)
		s_cmdCount[i] = 0;
	s_extentValid = FALSE;
}

void writeSparse(FILE *f, const std::map<Int, Int> &m)
{
	fputc(',', f);
	if (m.empty())
	{
		fputc('-', f);
		return;
	}
	Bool first = TRUE;
	for (std::map<Int, Int>::const_iterator it = m.begin(); it != m.end(); ++it)
	{
		fprintf(f, first ? "%d:%d" : ";%d:%d", it->first, it->second);
		first = FALSE;
	}
}

Int gridCell(const Coord3D *pos)
{
	if (!s_extentValid)
	{
		Region3D ext;
		TheTerrainLogic->getExtent(&ext);
		s_extLoX = ext.lo.x;
		s_extLoY = ext.lo.y;
		s_extSpanX = (ext.hi.x - ext.lo.x > 1.0f) ? (ext.hi.x - ext.lo.x) : 1.0f;
		s_extSpanY = (ext.hi.y - ext.lo.y > 1.0f) ? (ext.hi.y - ext.lo.y) : 1.0f;
		s_extentValid = TRUE;
	}
	Int ix = (Int)((pos->x - s_extLoX) / s_extSpanX * GRID_DIM);
	Int iy = (Int)((pos->y - s_extLoY) / s_extSpanY * GRID_DIM);
	if (ix < 0) ix = 0;
	if (ix >= GRID_DIM) ix = GRID_DIM - 1;
	if (iy < 0) iy = 0;
	if (iy >= GRID_DIM) iy = GRID_DIM - 1;
	return iy * GRID_DIM + ix;
}

void writeSample(FILE *f, UnsignedInt frame)
{
	Int unitCount[MAX_PLAYER_COUNT];
	Int unitValue[MAX_PLAYER_COUNT];
	Int structCount[MAX_PLAYER_COUNT];
	Int structValue[MAX_PLAYER_COUNT];
	Int heroicCount[MAX_PLAYER_COUNT];
	Int swCount[MAX_PLAYER_COUNT];
	Real swMaxReady[MAX_PLAYER_COUNT];
	Int queueCount[MAX_PLAYER_COUNT];
	Int queueValue[MAX_PLAYER_COUNT];

	std::map<Int, Int> comp[MAX_PLAYER_COUNT];
	std::map<Int, Int> ugrid[MAX_PLAYER_COUNT];
	std::map<Int, Int> sgrid[MAX_PLAYER_COUNT];
	Int i;
	for (i = 0; i < MAX_PLAYER_COUNT; ++i)
	{
		unitCount[i] = unitValue[i] = structCount[i] = structValue[i] = 0;
		heroicCount[i] = swCount[i] = queueCount[i] = queueValue[i] = 0;
		swMaxReady[i] = 0.0f;
	}

	for (Object *obj = TheGameLogic->getFirstObject(); obj != nullptr;
		 obj = obj->getNextObject())
	{
		if (obj->isEffectivelyDead())
			continue;
		if (obj->isKindOf(KINDOF_INERT) || obj->isKindOf(KINDOF_PROJECTILE))
			continue;
		Player *owner = obj->getControllingPlayer();
		if (owner == nullptr)
			continue;
		Int idx = owner->getPlayerIndex();
		if (idx < 0 || idx >= MAX_PLAYER_COUNT)
			continue;
		const ThingTemplate *tmpl = obj->getTemplate();
		Int cost = tmpl ? tmpl->friend_getBuildCost() : 0;
		if (tmpl && cost > 0)
			comp[idx][tmpl->getTemplateID()] += cost;
		if (obj->isKindOf(KINDOF_STRUCTURE))
		{
			structCount[idx] += 1;
			structValue[idx] += cost;
			if (cost > 0)
				sgrid[idx][gridCell(obj->getPosition())] += cost;

			if (obj->isKindOf(KINDOF_FS_SUPERWEAPON))
			{
				swCount[idx] += 1;
				for (BehaviorModule **m = obj->getBehaviorModules(); *m; ++m)
				{
					SpecialPowerModuleInterface *sp = (*m)->getSpecialPower();
					if (sp != nullptr && sp->getPercentReady() > swMaxReady[idx])
						swMaxReady[idx] = sp->getPercentReady();
				}
			}

			ProductionUpdateInterface *prod = obj->getProductionUpdateInterface();
			if (prod != nullptr)
			{
				queueCount[idx] += prod->getProductionCount();
				for (const ProductionEntry *e = prod->firstProduction();
					 e != nullptr; e = prod->nextProduction(e))
				{
					const ThingTemplate *pt = e->getProductionObject();
					if (pt != nullptr)
						queueValue[idx] += pt->friend_getBuildCost();
					else if (e->getProductionUpgrade() != nullptr)
						queueValue[idx] += e->getProductionUpgrade()->calcCostToBuild(owner);
				}
			}
		}
		else
		{
			unitCount[idx] += 1;
			unitValue[idx] += cost;
			if (cost > 0)
				ugrid[idx][gridCell(obj->getPosition())] += cost;
			if (obj->getVeterancyLevel() == LEVEL_HEROIC)
				heroicCount[idx] += 1;
		}
	}

	for (i = 0; i < ThePlayerList->getPlayerCount(); ++i)
	{
		Player *player = ThePlayerList->getNthPlayer(i);
		if (!isRealPlayer(player))
			continue;

		AsciiString name;
		name.translate(player->getPlayerDisplayName());
		sanitizeForCsv(name);
		AsciiString side = player->getPlayerTemplate()->getName();

		ScoreKeeper *score = player->getScoreKeeper();
		const Energy *energy = player->getEnergy();
		Int idx = player->getPlayerIndex();

		fprintf(f, "STATE,%u,%d,%s,%s,%u,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d"
			",%d,%d,%.3f,%d,%d,%u",
			frame, idx, name.str(), side.str(),
			player->getMoney()->countMoney(),
			score->getTotalMoneyEarned(), score->getTotalMoneySpent(),
			score->getTotalUnitsBuilt(), score->getTotalUnitsLost(),
			score->getTotalUnitsDestroyed(),
			score->getTotalBuildingsBuilt(), score->getTotalBuildingsLost(),
			score->getTotalBuildingsDestroyed(),
			score->getTotalTechBuildingsCaptured(),
			score->getTotalFactionBuildingsCaptured(),
			energy ? energy->getProduction() : 0,
			energy ? energy->getConsumption() : 0,
			unitCount[idx], unitValue[idx], structCount[idx], structValue[idx],
			heroicCount[idx], swCount[idx], swMaxReady[idx],
			queueCount[idx], queueValue[idx], s_cmdCount[idx]);
		writeSparse(f, comp[idx]);
		writeSparse(f, ugrid[idx]);
		writeSparse(f, sgrid[idx]);
		fputc('\n', f);
	}
}

} // namespace

//-------------------------------------------------------------------------------------------------
void WinPredictor::update()
{
	if (TheGameLogic == nullptr || !TheGameLogic->isInGame() || TheGameLogic->isInShellGame())
		return;
	if (isOnlineGame())
		return;

	UnsignedInt frame = TheGameLogic->getFrame();

	if (!s_matchStarted || frame < s_lastSeenFrame)
	{
		s_matchStarted = TRUE;
		startMatchFile();
	}
	s_lastSeenFrame = frame;

	if (!s_active)
		return;

	if (frame == 0 || (frame % SAMPLE_INTERVAL_FRAMES) != 0)
		return;

	FILE *f = fopen(s_csvPath, "a");
	if (f == nullptr)
		return;
	writeSample(f, frame);
	fclose(f);
}

//-------------------------------------------------------------------------------------------------
void WinPredictor::countCommand(const GameMessage *msg)
{
	if (isOnlineGame())
		return;
	if (msg == nullptr || msg->getType() == GameMessage::MSG_LOGIC_CRC)
		return;
	Int idx = msg->getPlayerIndex();
	if (idx >= 0 && idx < MAX_PLAYER_COUNT)
		s_cmdCount[idx] += 1;
}

//-------------------------------------------------------------------------------------------------
void WinPredictor::endMatch()
{
	if (s_active)
	{
		FILE *f = fopen(s_csvPath, "a");
		if (f != nullptr)
		{
			fprintf(f, "END,%u\n", s_lastSeenFrame);
			fclose(f);
		}
	}

	AsciiString path;
	if (getStateCsvPath(path))
		remove(path.str());

	s_active = FALSE;
	s_matchStarted = FALSE;
	s_lastSeenFrame = 0;
	s_extentValid = FALSE;
	s_csvPath[0] = 0;
	for (Int i = 0; i < MAX_PLAYER_COUNT; ++i)
		s_cmdCount[i] = 0;
}

//-------------------------------------------------------------------------------------------------
// Overlay
//-------------------------------------------------------------------------------------------------

namespace
{

const UnsignedInt PREDICTION_REFRESH_MS = 1000;

Bool s_havePrediction = FALSE;
Real s_probability = 0.5f;
char s_nameA[64] = {0};
char s_nameB[64] = {0};
UnsignedInt s_lastReadMs = 0;
DisplayString *s_overlayString = nullptr;

void readPredictionFile()
{
	AsciiString path = getExportDir();
	path.concat("prediction.txt");
	FILE *f = fopen(path.str(), "r");
	if (f == nullptr)
	{
		s_havePrediction = FALSE;
		return;
	}
	float p = 0.5f;
	char nameA[64] = {0};
	char nameB[64] = {0};
	int got = fscanf(f, "%f %63s %63s", &p, nameA, nameB);
	fclose(f);
	if (got < 1 || p < 0.0f || p > 1.0f)
	{
		s_havePrediction = FALSE;
		return;
	}
	s_probability = p;
	strlcpy(s_nameA, (got >= 2) ? nameA : "", ARRAY_SIZE(s_nameA));
	strlcpy(s_nameB, (got >= 3) ? nameB : "", ARRAY_SIZE(s_nameB));
	s_havePrediction = TRUE;
}

Color colorForPlayerName(const char *name, UnsignedByte alpha, Color fallback)
{
	if (name == nullptr || name[0] == 0 || ThePlayerList == nullptr)
		return fallback;

	for (Int i = 0; i < ThePlayerList->getPlayerCount(); ++i)
	{
		Player *player = ThePlayerList->getNthPlayer(i);
		if (player == nullptr)
			continue;

		AsciiString pname;
		pname.translate(player->getPlayerDisplayName());
		sanitizeForCsv(pname);

		char key[64];
		const char *src = pname.str();
		Int j = 0;
		for (Int k = 0; src[k] != 0 && j < 30; ++k)
			key[j++] = (src[k] == ' ') ? '_' : src[k];
		key[j] = 0;

		if (stricmp(key, name) == 0)
		{
			UnsignedByte r, g, b, a;
			GameGetColorComponents(player->getPlayerColor(), &r, &g, &b, &a);
			return GameMakeColor(r, g, b, alpha);
		}
	}

	return fallback;
}

} // namespace

void WinPredictor::drawOverlay()
{
	if (TheGlobalData == nullptr || TheGlobalData->m_headless)
		return;
	if (TheDisplay == nullptr || TheDisplayStringManager == nullptr)
		return;
	if (TheGameLogic == nullptr || !TheGameLogic->isInGame() || TheGameLogic->isInShellGame())
		return;
	if (isOnlineGame())
		return;

	const UnsignedInt nowMs = timeGetTime();
	if (s_lastReadMs == 0 || (nowMs - s_lastReadMs) >= PREDICTION_REFRESH_MS)
	{
		s_lastReadMs = nowMs;
		readPredictionFile();
	}

	if (!s_havePrediction)
		return;

	const Int barWidth = 300;
	const Int barHeight = 14;
	const Int x = (Int)TheDisplay->getWidth() / 2 - barWidth / 2;
	const Int y = 4;
	const Int leftWidth = (Int)(barWidth * s_probability + 0.5f);

	const Color leftColor = colorForPlayerName(s_nameA, 220, GameMakeColor(70, 140, 255, 220));
	const Color rightColor = colorForPlayerName(s_nameB, 220, GameMakeColor(235, 80, 70, 220));
	TheDisplay->drawFillRect(x - 2, y - 2, barWidth + 4, barHeight + 4,
		GameMakeColor(0, 0, 0, 160));
	TheDisplay->drawFillRect(x, y, leftWidth, barHeight, leftColor);
	TheDisplay->drawFillRect(x + leftWidth, y, barWidth - leftWidth, barHeight, rightColor);

	if (s_overlayString == nullptr)
	{
		s_overlayString = TheDisplayStringManager->newDisplayString();
		Int fontSize = TheGlobalLanguageData ? TheGlobalLanguageData->adjustFontSize(10) : 10;
		GameFont *font = TheWindowManager ?
			TheWindowManager->winFindFont(AsciiString("Arial"), fontSize, TRUE) : nullptr;
		if (font != nullptr)
			s_overlayString->setFont(font);
	}

	UnicodeString text;
	text.format(L"%hs %.0f%%  vs  %.0f%% %hs", s_nameA,
		s_probability * 100.0f, (1.0f - s_probability) * 100.0f, s_nameB);
	s_overlayString->setText(text);
	const Int textX = (Int)TheDisplay->getWidth() / 2 - s_overlayString->getWidth() / 2;
	s_overlayString->draw(textX, y + barHeight + 4,
		GameMakeColor(255, 255, 255, 255), GameMakeColor(0, 0, 0, 255));
}
