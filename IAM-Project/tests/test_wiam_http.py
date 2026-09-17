import unittest
from unittest.mock import Mock, patch

from renseigner import run_renseigner
from wiam_http import WiamHttpClient


def response(url: str, html: str):
    item = Mock()
    item.url = url
    item.content = html.encode("utf-8")
    item.raise_for_status.return_value = None
    return item


class WiamHttpClientTests(unittest.TestCase):
    @patch("wiam_http.requests.Session")
    def test_authenticates_and_reads_second_result_cell(self, session_factory):
        login_page = response(
            "https://wiam/login.jsp",
            """<form method="post" action="/login">
            <input id="login" name="login"><input id="password" name="password" type="password">
            </form>""",
        )
        home_page = response("https://wiam/accueil.jsp", "<p>Accueil</p>")
        search_page = response(
            "https://wiam/commande_recherche_critere.jsp",
            """<form method="get" action="/commande_recherche_critere.jsp">
            <input type="radio" name="critere" value="1">
            <input name="num_commande">
            </form>""",
        )
        result_page = response(
            "https://wiam/commande_recherche_critere.jsp",
            '<table><td class="datalistfield">CMD</td><td class="datalistfield">I12345678</td></table>',
        )
        session = session_factory.return_value
        session.request.side_effect = [login_page, home_page, search_page, result_page]
        client = WiamHttpClient({
            "wiam_url": "https://wiam/commande_recherche_critere.jsp",
            "wiam_username": "user",
            "wiam_password": "secret",
            "timeout_seconds": 10,
        })

        self.assertEqual(client.lookup_login("100123456"), "I12345678")
        login_call = session.request.call_args_list[1]
        self.assertEqual(login_call.kwargs["data"]["login"], "user")
        self.assertEqual(login_call.kwargs["data"]["password"], "secret")
        search_call = session.request.call_args_list[3]
        self.assertEqual(search_call.kwargs["params"]["num_commande"], "100123456")
        self.assertEqual(search_call.kwargs["params"]["critere"], "1")

    @patch("renseigner.close_driver")
    @patch("renseigner.build_driver")
    @patch("renseigner.WiamHttpClient")
    def test_cmd_only_http_mode_does_not_open_chrome(
        self, client_type, build_driver, _close_driver
    ):
        client_type.return_value.lookup_login.return_value = "I12345678"
        results = []

        run_renseigner(
            config={"execution_mode": "http"},
            rows=[{"excel_row": 1, "mode": "CMD", "input": "100123456"}],
            degroupage={},
            stopped=lambda: False,
            on_result=lambda _index, item: results.append(item),
            on_log=lambda _level, _message: None,
        )

        build_driver.assert_not_called()
        self.assertEqual(results[0]["login"], "I12345678")
        self.assertEqual(results[0]["source"], "WIAM HTTP")

    @patch("renseigner.close_driver")
    @patch("renseigner.collect_wiam_login", return_value="I87654321")
    @patch("renseigner.build_driver", return_value=Mock())
    @patch("renseigner.WiamHttpClient")
    def test_http_failure_falls_back_to_selenium(
        self, client_type, build_driver, collect_wiam, _close_driver
    ):
        client_type.return_value.lookup_login.side_effect = ValueError("form changed")
        results, logs = [], []

        run_renseigner(
            config={"execution_mode": "http", "headless": False},
            rows=[{"excel_row": 1, "mode": "CMD", "input": "100123456"}],
            degroupage={},
            stopped=lambda: False,
            on_result=lambda _index, item: results.append(item),
            on_log=lambda level, message: logs.append((level, message)),
        )

        build_driver.assert_called_once()
        collect_wiam.assert_called_once()
        self.assertEqual(results[0]["source"], "WIAM Selenium (repli)")
        self.assertTrue(any(level == "WARNING" for level, _message in logs))


if __name__ == "__main__":
    unittest.main()
