import json
import math
import sqlite3
from decimal import Decimal, localcontext
from pathlib import Path
from threading import Event
import pytest
from corpus_app.tagged_import import import_tagged
from corpus_app.statistics.keyness import contingency, analyze_keyness, check_compatible


def make_corpus(tmp_path, name, content):
    path = tmp_path / f'{name}.txt'
    path.write_text(content, encoding='utf-8')
    return import_tagged([path], {'mode':'slash'}, tmp_path / 'morph')


def decimal_oracle(a, c, n1, n2):
    with localcontext() as context:
        context.prec = 50
        obs = [Decimal(a), Decimal(n1-a), Decimal(c), Decimal(n2-c)]
        n1, n2, total = Decimal(n1), Decimal(n2), Decimal(n1+n2)
        expected = [n1*(obs[0]+obs[2])/total, n1*(obs[1]+obs[3])/total,
                    n2*(obs[0]+obs[2])/total, n2*(obs[1]+obs[3])/total]
        g = 2 * sum(o*(o/e).ln() for o,e in zip(obs,expected) if o and e)
        chi = sum((o-e)**2/e for o,e in zip(obs,expected) if e)
        return float(g), float(chi)


@pytest.mark.parametrize('counts', [(10,20,100,100),(0,3,100,50),(8,0,8,20),(1,2,1,2),(5,5,50,50)])
def test_contingency_against_high_precision_and_symmetry(counts):
    a,c,n1,n2 = counts
    expected = decimal_oracle(*counts)
    for metric, oracle in zip(('G²','χ²'), expected):
        value, direction, minimum, low = contingency(*counts, metric)
        assert value == pytest.approx(oracle, abs=1e-12)
        reversed_value, reverse_direction, _, _ = contingency(c,a,n2,n1,metric)
        assert value == pytest.approx(reversed_value, abs=1e-12)
        assert direction == ('대상' if a*n2>c*n1 else '참조' if a*n2<c*n1 else '동일')
        assert reverse_direction == {'대상':'참조','참조':'대상','동일':'동일'}[direction]
        assert low == (minimum<5)
    with pytest.raises(ValueError):
        contingency(a,c,0,n2,'G²')


def test_union_denominators_single_sided_and_counts_reuse(tmp_path, monkeypatch):
    target = make_corpus(tmp_path,'target','밥/NNG 밥/NNG 먹/VV\n')
    reference = make_corpus(tmp_path,'reference','국/NNG 먹/VV 먹/VV\n')
    settings = {'n':1,'metric':'G²','confirm_external':True}
    root = tmp_path/'results'
    first = analyze_keyness(target.path,reference.path,settings,root)
    assert first.metadata['target_ngrams']==first.metadata['reference_ngrams']==3
    rows = {row[0]: row for row in first.rows}
    assert set(rows)=={'밥','먹','국'}
    assert rows['밥'][1:3]==[2,0] and rows['국'][1:3]==[0,1]
    assert rows['밥'][3]==pytest.approx(2/3*1000000)
    assert rows['밥'][6]=='대상' and rows['국'][6]=='참조'
    assert all(row[8]=='예' for row in first.rows)
    assert not any(first.metadata['counts_reused'].values())
    def forbidden(*args,**kwargs):
        raise AssertionError('same input/settings must reuse ngram counts')
    with monkeypatch.context() as patch:
        patch.setattr('corpus_app.statistics.keyness.analyze_statistics',forbidden)
        again = analyze_keyness(target.path,reference.path,{**settings,'metric':'χ²'},root)
        assert all(again.metadata['counts_reused'].values())
        assert again.columns[5]=='χ²'
    # Changing n invalidates the count cache and its denominator.
    bigram = analyze_keyness(target.path,reference.path,{**settings,'n':2},root)
    assert bigram.metadata['target_ngrams']==bigram.metadata['reference_ngrams']==2
    assert not any(bigram.metadata['counts_reused'].values())
    # A changed immutable source DB must not reuse stale counts.
    with sqlite3.connect(target.path) as db:
        db.execute('UPDATE utterances SET tokens=? WHERE seq=1', (json.dumps([['밥','NNG'],['먹','VV'],['국','NNG']]),))
    changed = analyze_keyness(target.path,reference.path,settings,root)
    assert not changed.metadata['counts_reused']['target'] and changed.metadata['counts_reused']['reference']


def test_compatibility_paths_defaults_dictionaries_and_external_confirmation():
    base = {'name':'kiwi','options':{},'engine_version':'0.24.1/model-0.24.0','model_type':'cong','preprocessing':'identity',
            'source_folder':'/target','field_path':['utterances',None,'text']}
    other = {**base,'source_folder':'/ref','field_path':['document','text'],
             'options':{'normalize_coda':False,'split_complex':False,'compatible_jamo':False,'user_dictionary':'# empty'}}
    assert check_compatible(base,other)['mode']=='recorded_settings_match'
    for update in ({'engine_version':'different'},{'options':{'normalize_coda':True}},
                   {'options':{'user_dictionary':'방언 NNP 5'}},{'preprocessing':'NFC'}):
        with pytest.raises(ValueError,match='다릅니다'):
            check_compatible(base,{**other,**update},True)
    imported = {'name':'imported','preprocessing':'none; forms and POS preserved'}
    with pytest.raises(ValueError,match='확인'):
        check_compatible(imported,imported)
    assert check_compatible(imported,imported,True)['mode']=='user_confirmed'
    with pytest.raises(ValueError):
        check_compatible(base,imported,True)
    remote={'name':'bareun','options':{},'engine_version':'2.1.0','model_type':'hosted/model-not-exposed','preprocessing':'identity'}
    with pytest.raises(ValueError,match='확인'):
        check_compatible(remote,remote)


def test_zero_ngrams_explanation_and_self_comparison(tmp_path):
    target=make_corpus(tmp_path,'one','밥/NNG\n')
    reference=make_corpus(tmp_path,'two','밥/NNG 먹/VV\n')
    settings={'n':2,'metric':'χ²','confirm_external':True}
    empty=analyze_keyness(target.path,reference.path,settings,tmp_path/'results')
    assert not empty.rows and empty.metadata['target_ngrams']==0 and empty.metadata['reference_ngrams']==1
    assert '대상' in empty.metadata['note'] and '0' in empty.metadata['note']
    same=analyze_keyness(reference.path,reference.path,{**settings,'n':1},tmp_path/'results')
    assert all(row[5]==pytest.approx(0) and row[6]=='동일' for row in same.rows)


def test_keyness_cancel_leaves_no_incomplete_results(tmp_path):
    target=make_corpus(tmp_path,'one',('밥/NNG 먹/VV\n'*500))
    reference=make_corpus(tmp_path,'two','밥/NNG\n')
    cancel=Event()
    result=analyze_keyness(target.path,reference.path,{'n':1,'confirm_external':True},tmp_path/'out',cancel,
                           lambda *args:cancel.set())
    assert result.cancelled
    assert not list((tmp_path/'out').glob('keyness-*.sqlite'))
    assert not list((tmp_path/'out').rglob('*.tmp'))


def test_different_json_fields_share_native_analyzer_settings_without_reanalysis(tmp_path,monkeypatch):
    from corpus_app import morphology
    from corpus_app.analyzers import Morpheme
    class Words:
        def analyze(self,text):
            return [Morpheme(word,'NNG') for word in text.split()]
    monkeypatch.setattr(morphology,'create',lambda *args:Words())
    target_dir=tmp_path/'target';reference_dir=tmp_path/'reference';target_dir.mkdir();reference_dir.mkdir()
    (target_dir/'one.json').write_text(json.dumps({'utterances':[{'text':'밥 밥 먹'}]},ensure_ascii=False),encoding='utf-8')
    (reference_dir/'one.json').write_text(json.dumps({'document':{'text':'국 먹 먹'}},ensure_ascii=False),encoding='utf-8')
    config={'name':'kiwi','options':{}}
    target=morphology.analyze_corpus(target_dir,['utterances',None,'text'],config,tmp_path/'morph')
    reference=morphology.analyze_corpus(reference_dir,['document','text'],config,tmp_path/'morph')
    def forbidden(*args,**kwargs):
        raise AssertionError('keyness must not call an analyzer')
    monkeypatch.setattr(morphology,'create',forbidden)
    result=analyze_keyness(target.path,reference.path,{'n':1},tmp_path/'out')
    assert result.metadata['target_ngrams']==result.metadata['reference_ngrams']==3
    assert result.metadata['compatibility']['mode']=='recorded_settings_match'
    assert result.metadata['producer']['field_path']!=result.metadata['reference_producer']['field_path']


def test_low_expected_filter_queries_all_candidates(tmp_path):
    from corpus_app.statistics.analysis import load_statistics
    target=make_corpus(tmp_path,'target',' '.join(['공통/NNG']*10+['기본/NNG']*90+['희귀/NNG'])+'\n')
    reference=make_corpus(tmp_path,'reference',' '.join(['공통/NNG']*20+['기본/NNG']*80)+'\n')
    result=analyze_keyness(target.path,reference.path,{'n':1,'metric':'χ²','confirm_external':True},tmp_path/'out')
    assert result.metadata['result_count']==3 and result.metadata['low_expected_count']==1
    filtered=load_statistics(result.path,'score',10,low_expected_only=True)
    assert len(filtered.rows)==1 and filtered.rows[0][0]=='희귀' and filtered.rows[0][8]=='예'
