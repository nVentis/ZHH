#ifndef FinalStateRecorder_h
#define FinalStateRecorder_h 1

#include "marlin/Processor.h"
#include "IMPL/LCCollectionVec.h"
#include "lcio.h"
#include <string>
#include <fstream>
#include <TFile.h>
#include <TTree.h>
#include <vector>
#include "nlohmann/json.hpp"
#include "FinalStateResolver.h"

class TFile;
class TTree;

using namespace lcio;
using namespace marlin;
using jsonf = nlohmann::json;

struct ERROR_CODES {
	enum Values: int {
		UNINITIALIZED = 9999,
		OK = 0,
		COLLECTION_NOT_FOUND = 1,
		PROCESS_NOT_FOUND = 2,
		UNKNOWN_ERROR = 3,
	};
};


class FinalStateRecorder : public Processor
{
	private:
		void register_process(FinalStateResolver* resolver) { m_resolvers[resolver->get_process_name()] = resolver;  };
		std::map<std::string, FinalStateResolver*> m_resolvers{};

	public:

		virtual Processor*  newProcessor()
		{
			return new FinalStateRecorder;
		}
		FinalStateRecorder();
		virtual ~FinalStateRecorder() = default;
		FinalStateRecorder(const FinalStateRecorder&) = delete;
		FinalStateRecorder& operator=(const FinalStateRecorder&) = delete;
		virtual void init();
		virtual void Clear();
		virtual void processRunHeader( LCRunHeader*  /*run*/);
		virtual void processEvent( EVENT::LCEvent *pLCEvent );
		virtual void check();
		virtual void end();
		
	 protected:
		
		/**
		 * Add the expected output collections
		 */
		
		/** Input collection name.
		 */
		std::string m_mcParticleCollection{};
		std::string m_mcParticleCollectionAlt{};
		std::string m_outputJsonFile{};
		std::string m_outputRootFile{};

		int m_nRun;
		int m_nEvt;
		int m_nEvtSum;
		int m_errorCode;
		
		std::vector<int> m_final_states{};
		std::vector<int> m_final_states_h_decay{};
		std::map<int, int> m_final_state_counts {
			{ 1, 0 }, // d
			{ 2, 0 }, // u
			{ 3, 0 }, // s
			{ 4, 0 }, // c
			{ 5, 0 }, // b
			{ 6, 0 }, // t
			{ 11, 0 }, // e
			{ 12, 0 }, // ve
			{ 13, 0 }, // µ
			{ 14, 0 }, // vµ
			{ 15, 0 }, // tau
			{ 16, 0 }, // vtau
			{ 22, 0 }, // γ
			{ 23, 0 }, // Z
			{ 24, 0 }, // W
			{ 25, 0 } // h
		};

		int m_process{};
		int m_event_category{};
		int m_event_category_zhh{};
		int m_n_fermion{};
		int m_n_higgs{};

		// Output ROOT file
		TFile *m_pTFile{};
		TTree *m_pTTree{};

		// Output JSON file
		jsonf m_jsonFile{};

};

#endif
